from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from models import BattleRound
from storage import JsonStorage


@dataclass
class BattleUpdateResult:
    round_started: bool
    current_leader_user_id: int
    participant_count: int
    started_at: datetime
    last_activity_at: datetime


class BattleManager:
    def __init__(self, storage: JsonStorage) -> None:
        self._storage = storage
        self._active_round: BattleRound | None = None

    def load_state(self) -> None:
        self._active_round = self._storage.load_active_round()

    def save_state(self) -> None:
        self._storage.save_active_round(self._active_round)

    def has_active_round(self) -> bool:
        return self._active_round is not None

    def get_active_round(self) -> BattleRound | None:
        return self._active_round

    def handle_gif_message(self, channel_id: int, user_id: int) -> BattleUpdateResult:
        now = datetime.now(timezone.utc)

        if self._active_round is None:
            self._active_round = BattleRound.create(channel_id=channel_id, user_id=user_id)
            self.save_state()
            return BattleUpdateResult(
                round_started=True,
                current_leader_user_id=self._active_round.last_gif_user_id,
                participant_count=len(self._active_round.participant_ids),
                started_at=self._active_round.started_at,
                last_activity_at=self._active_round.last_activity_at,
            )

        if self._active_round.channel_id != channel_id:
            raise ValueError(
                f"BattleManager received channel_id={channel_id}, "
                f"but active round is for channel_id={self._active_round.channel_id}."
            )

        self._active_round.last_activity_at = now
        self._active_round.last_gif_user_id = user_id
        self._active_round.participant_ids.add(user_id)
        self.save_state()

        return BattleUpdateResult(
            round_started=False,
            current_leader_user_id=self._active_round.last_gif_user_id,
            participant_count=len(self._active_round.participant_ids),
            started_at=self._active_round.started_at,
            last_activity_at=self._active_round.last_activity_at,
        )

    def get_deadline(self, timeout_seconds: int) -> datetime | None:
        if self._active_round is None:
            return None
        return self._active_round.last_activity_at + timedelta(seconds=timeout_seconds)

    def is_round_expired(self, timeout_seconds: int) -> bool:
        if self._active_round is None:
            return False

        now = datetime.now(timezone.utc)
        deadline = self.get_deadline(timeout_seconds)

        if deadline is None:
            return False

        return now >= deadline

    def get_seconds_until_timeout(self, timeout_seconds: int) -> int | None:
        if self._active_round is None:
            return None

        deadline = self.get_deadline(timeout_seconds)
        if deadline is None:
            return None

        now = datetime.now(timezone.utc)
        remaining = (deadline - now).total_seconds()

        return max(0, int(remaining))

    def end_round(self) -> BattleRound | None:
        finished_round = self._active_round
        self._active_round = None
        self.save_state()
        return finished_round