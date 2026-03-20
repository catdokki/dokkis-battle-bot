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