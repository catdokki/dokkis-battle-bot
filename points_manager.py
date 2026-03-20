from __future__ import annotations

from dataclasses import dataclass

from models import BattleRound, UserStats
from storage import JsonStorage


WIN_POINTS = 10
PARTICIPATION_POINTS = 2


@dataclass
class RoundAwardSummary:
    winner_user_id: int
    awarded_user_ids: list[int]
    points_awarded_by_user_id: dict[int, int]
    stats_by_user_id: dict[int, UserStats]


class PointsManager:
    def __init__(self, storage: JsonStorage) -> None:
        self._storage = storage
        self._stats_by_user_id: dict[int, UserStats] = {}

    def load_state(self) -> None:
        self._stats_by_user_id = self._storage.load_user_stats()

    def save_state(self) -> None:
        self._storage.save_user_stats(self._stats_by_user_id)

    def get_or_create_user_stats(self, user_id: int) -> UserStats:
        stats = self._stats_by_user_id.get(user_id)
        if stats is None:
            stats = UserStats(user_id=user_id)
            self._stats_by_user_id[user_id] = stats
        return stats

    def award_round_points(self, battle_round: BattleRound) -> RoundAwardSummary:
        awarded_user_ids = sorted(battle_round.participant_ids)
        points_awarded_by_user_id: dict[int, int] = {}

        for user_id in awarded_user_ids:
            stats = self.get_or_create_user_stats(user_id)
            stats.rounds_joined += 1
            stats.total_points += PARTICIPATION_POINTS
            points_awarded_by_user_id[user_id] = PARTICIPATION_POINTS

        winner_stats = self.get_or_create_user_stats(battle_round.last_gif_user_id)
        winner_stats.rounds_won += 1
        winner_stats.total_points += WIN_POINTS
        points_awarded_by_user_id[battle_round.last_gif_user_id] = (
            points_awarded_by_user_id.get(battle_round.last_gif_user_id, 0) + WIN_POINTS
        )

        self.save_state()

        return RoundAwardSummary(
            winner_user_id=battle_round.last_gif_user_id,
            awarded_user_ids=awarded_user_ids,
            points_awarded_by_user_id=points_awarded_by_user_id,
            stats_by_user_id={
                user_id: self._stats_by_user_id[user_id]
                for user_id in awarded_user_ids
            },
        )

    def get_user_stats(self, user_id: int) -> UserStats:
        return self.get_or_create_user_stats(user_id)

    def get_leaderboard(self, limit: int = 10) -> list[UserStats]:
        return sorted(
            self._stats_by_user_id.values(),
            key=lambda stats: (-stats.total_points, -stats.rounds_won, stats.user_id),
        )[:limit]