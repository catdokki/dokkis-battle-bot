from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BattleRound:
    channel_id: int
    started_at: datetime
    last_activity_at: datetime
    last_gif_user_id: int
    participant_ids: set[int] = field(default_factory=set)

    @classmethod
    def create(cls, channel_id: int, user_id: int) -> "BattleRound":
        now = datetime.now(timezone.utc)
        return cls(
            channel_id=channel_id,
            started_at=now,
            last_activity_at=now,
            last_gif_user_id=user_id,
            participant_ids={user_id},
        )

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "started_at": self.started_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat(),
            "last_gif_user_id": self.last_gif_user_id,
            "participant_ids": sorted(self.participant_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BattleRound":
        return cls(
            channel_id=int(data["channel_id"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            last_activity_at=datetime.fromisoformat(data["last_activity_at"]),
            last_gif_user_id=int(data["last_gif_user_id"]),
            participant_ids={int(user_id) for user_id in data.get("participant_ids", [])},
        )


@dataclass
class UserStats:
    user_id: int
    total_points: int = 0
    rounds_joined: int = 0
    rounds_won: int = 0
    current_win_streak: int = 0
    best_win_streak: int = 0

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "total_points": self.total_points,
            "rounds_joined": self.rounds_joined,
            "rounds_won": self.rounds_won,
            "current_win_streak": self.current_win_streak,
            "best_win_streak": self.best_win_streak,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserStats":
        return cls(
            user_id=int(data["user_id"]),
            total_points=int(data.get("total_points", 0)),
            rounds_joined=int(data.get("rounds_joined", 0)),
            rounds_won=int(data.get("rounds_won", 0)),
            current_win_streak=int(data.get("current_win_streak", 0)),
            best_win_streak=int(data.get("best_win_streak", 0)),
        )