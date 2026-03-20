from __future__ import annotations

from dataclasses import dataclass

from models import BattleRound, UserStats
from storage import JsonStorage


WIN_POINTS = 10
PARTICIPATION_POINTS = 2
STREAK_BONUS_THRESHOLD = 2
STREAK_BONUS_POINTS = 5
REACTION_BONUS_CAP = 5


@dataclass(frozen=True)
class LevelConfig:
    participation_xp: int = 15
    win_xp: int = 50
    streak_bonus_xp: int = 20
    reaction_xp_per_bonus_point: int = 2
    level_base_xp: int = 100
    level_step_xp: int = 50


@dataclass
class UserLevelProgress:
    level: int
    total_xp: int
    xp_into_level: int
    xp_needed_for_next_level: int
    progress_percent: float


@dataclass
class UserAwardBreakdown:
    user_id: int
    points_earned: int = 0
    xp_earned: int = 0
    levels_gained: int = 0
    new_level: int = 1


@dataclass
class RoundAwardSummary:
    winner_user_id: int
    awarded_user_ids: list[int]
    points_awarded_by_user_id: dict[int, int]
    xp_awarded_by_user_id: dict[int, int]
    stats_by_user_id: dict[int, UserStats]
    level_progress_by_user_id: dict[int, UserLevelProgress]
    level_ups_by_user_id: dict[int, int]
    streak_bonus_awarded: bool
    winner_current_streak: int
    reaction_bonus_by_user_id: dict[int, int]


class PointsManager:
    def __init__(self, storage: JsonStorage, level_config: LevelConfig | None = None) -> None:
        self._storage = storage
        self._stats_by_user_id: dict[int, UserStats] = {}
        self._level_config = level_config or LevelConfig()

    def load_state(self) -> None:
        self._stats_by_user_id = self._storage.load_user_stats()
        self._reconcile_all_levels()
        self.save_state()

    def save_state(self) -> None:
        self._storage.save_user_stats(self._stats_by_user_id)

    def get_or_create_user_stats(self, user_id: int) -> UserStats:
        stats = self._stats_by_user_id.get(user_id)
        if stats is None:
            stats = UserStats(user_id=user_id)
            self._stats_by_user_id[user_id] = stats
        return stats

    def _xp_required_for_level(self, level: int) -> int:
        return self._level_config.level_base_xp + ((level - 1) * self._level_config.level_step_xp)

    def _recalculate_level_from_total_xp(self, total_xp: int) -> int:
        level = 1
        xp_remaining = total_xp

        while xp_remaining >= self._xp_required_for_level(level):
            xp_remaining -= self._xp_required_for_level(level)
            level += 1

        return level

    def _reconcile_all_levels(self) -> None:
        for stats in self._stats_by_user_id.values():
            stats.level = self._recalculate_level_from_total_xp(stats.total_xp)

    def get_level_progress(self, user_id: int) -> UserLevelProgress:
        stats = self.get_or_create_user_stats(user_id)
        xp_remaining = stats.total_xp
        current_level = 1

        while xp_remaining >= self._xp_required_for_level(current_level):
            xp_remaining -= self._xp_required_for_level(current_level)
            current_level += 1

        xp_needed = self._xp_required_for_level(current_level)
        progress_percent = 0.0 if xp_needed == 0 else (xp_remaining / xp_needed) * 100

        return UserLevelProgress(
            level=current_level,
            total_xp=stats.total_xp,
            xp_into_level=xp_remaining,
            xp_needed_for_next_level=xp_needed,
            progress_percent=progress_percent,
        )

    def _award_xp(self, user_id: int, xp_amount: int) -> tuple[UserStats, int]:
        stats = self.get_or_create_user_stats(user_id)
        previous_level = stats.level
        stats.total_xp += xp_amount
        stats.level = self._recalculate_level_from_total_xp(stats.total_xp)
        return stats, max(0, stats.level - previous_level)

    def _update_win_streaks(self, winner_user_id: int) -> UserStats:
        winner_stats = self.get_or_create_user_stats(winner_user_id)

        for user_id, stats in self._stats_by_user_id.items():
            if user_id == winner_user_id:
                continue
            stats.current_win_streak = 0

        winner_stats.current_win_streak += 1
        winner_stats.best_win_streak = max(
            winner_stats.best_win_streak,
            winner_stats.current_win_streak,
        )

        return winner_stats

    def _calculate_reaction_bonus_by_user_id(
        self,
        battle_round: BattleRound,
    ) -> dict[int, int]:
        raw_reaction_counts_by_user_id: dict[int, int] = {}

        for gif_message in battle_round.gif_messages.values():
            reaction_count = gif_message.count_non_self_reactions()
            raw_reaction_counts_by_user_id[gif_message.author_id] = (
                raw_reaction_counts_by_user_id.get(gif_message.author_id, 0)
                + reaction_count
            )

        return {
            user_id: min(count, REACTION_BONUS_CAP)
            for user_id, count in raw_reaction_counts_by_user_id.items()
            if count > 0
        }

    def award_round_points(self, battle_round: BattleRound) -> RoundAwardSummary:
        awarded_user_ids = sorted(battle_round.participant_ids)
        points_awarded_by_user_id: dict[int, int] = {}
        xp_awarded_by_user_id: dict[int, int] = {}
        level_ups_by_user_id: dict[int, int] = {}

        def add_xp(user_id: int, xp_amount: int) -> None:
            if xp_amount <= 0:
                return
            _, levels_gained = self._award_xp(user_id, xp_amount)
            xp_awarded_by_user_id[user_id] = xp_awarded_by_user_id.get(user_id, 0) + xp_amount
            if levels_gained > 0:
                level_ups_by_user_id[user_id] = level_ups_by_user_id.get(user_id, 0) + levels_gained

        for user_id in awarded_user_ids:
            stats = self.get_or_create_user_stats(user_id)
            stats.rounds_joined += 1
            stats.total_points += PARTICIPATION_POINTS
            points_awarded_by_user_id[user_id] = PARTICIPATION_POINTS
            add_xp(user_id, self._level_config.participation_xp)

        winner_stats = self.get_or_create_user_stats(battle_round.last_gif_user_id)
        winner_stats.rounds_won += 1
        winner_stats.total_points += WIN_POINTS
        points_awarded_by_user_id[battle_round.last_gif_user_id] = (
            points_awarded_by_user_id.get(battle_round.last_gif_user_id, 0) + WIN_POINTS
        )
        add_xp(battle_round.last_gif_user_id, self._level_config.win_xp)

        winner_stats = self._update_win_streaks(battle_round.last_gif_user_id)
        streak_bonus_awarded = winner_stats.current_win_streak >= STREAK_BONUS_THRESHOLD

        if streak_bonus_awarded:
            winner_stats.total_points += STREAK_BONUS_POINTS
            points_awarded_by_user_id[battle_round.last_gif_user_id] = (
                points_awarded_by_user_id.get(battle_round.last_gif_user_id, 0)
                + STREAK_BONUS_POINTS
            )
            add_xp(battle_round.last_gif_user_id, self._level_config.streak_bonus_xp)

        reaction_bonus_by_user_id = self._calculate_reaction_bonus_by_user_id(battle_round)

        for user_id, reaction_bonus in reaction_bonus_by_user_id.items():
            stats = self.get_or_create_user_stats(user_id)
            stats.total_points += reaction_bonus
            points_awarded_by_user_id[user_id] = (
                points_awarded_by_user_id.get(user_id, 0) + reaction_bonus
            )
            add_xp(user_id, reaction_bonus * self._level_config.reaction_xp_per_bonus_point)

        self.save_state()

        users_to_include = set(awarded_user_ids) | set(reaction_bonus_by_user_id.keys())

        return RoundAwardSummary(
            winner_user_id=battle_round.last_gif_user_id,
            awarded_user_ids=awarded_user_ids,
            points_awarded_by_user_id=points_awarded_by_user_id,
            xp_awarded_by_user_id=xp_awarded_by_user_id,
            stats_by_user_id={user_id: self._stats_by_user_id[user_id] for user_id in users_to_include},
            level_progress_by_user_id={user_id: self.get_level_progress(user_id) for user_id in users_to_include},
            level_ups_by_user_id=level_ups_by_user_id,
            streak_bonus_awarded=streak_bonus_awarded,
            winner_current_streak=winner_stats.current_win_streak,
            reaction_bonus_by_user_id=reaction_bonus_by_user_id,
        )

    def get_user_stats(self, user_id: int) -> UserStats:
        return self.get_or_create_user_stats(user_id)

    def get_leaderboard(self, limit: int = 10) -> list[UserStats]:
        return sorted(
            self._stats_by_user_id.values(),
            key=lambda stats: (
                -stats.level,
                -stats.total_xp,
                -stats.total_points,
                -stats.rounds_won,
                -stats.best_win_streak,
                stats.user_id,
            ),
        )[:limit]
