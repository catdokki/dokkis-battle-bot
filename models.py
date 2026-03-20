from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class GifMessage:
    message_id: int
    author_id: int
    emoji_reactors: dict[str, set[int]] = field(default_factory=dict)

    def add_reaction(self, emoji_key: str, reactor_user_id: int) -> bool:
        reactors = self.emoji_reactors.setdefault(emoji_key, set())
        before = len(reactors)
        reactors.add(reactor_user_id)
        return len(reactors) > before

    def remove_reaction(self, emoji_key: str, reactor_user_id: int) -> bool:
        reactors = self.emoji_reactors.get(emoji_key)
        if not reactors:
            return False

        if reactor_user_id not in reactors:
            return False

        reactors.remove(reactor_user_id)

        if not reactors:
            del self.emoji_reactors[emoji_key]

        return True

    def count_non_self_reactions(self) -> int:
        total = 0
        for reactors in self.emoji_reactors.values():
            total += sum(1 for user_id in reactors if user_id != self.author_id)
        return total

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "author_id": self.author_id,
            "emoji_reactors": {
                emoji_key: sorted(user_ids)
                for emoji_key, user_ids in self.emoji_reactors.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GifMessage":
        return cls(
            message_id=int(data["message_id"]),
            author_id=int(data["author_id"]),
            emoji_reactors={
                str(emoji_key): {int(user_id) for user_id in user_ids}
                for emoji_key, user_ids in data.get("emoji_reactors", {}).items()
            },
        )


@dataclass
class BattleRound:
    channel_id: int
    started_at: datetime
    last_activity_at: datetime
    last_gif_user_id: int
    round_number: int = 0
    participant_ids: set[int] = field(default_factory=set)
    gif_messages: dict[int, GifMessage] = field(default_factory=dict)
    status_message_id: int | None = None

    @classmethod
    def create(cls, channel_id: int, user_id: int, message_id: int) -> "BattleRound":
        now = datetime.now(timezone.utc)
        gif_message = GifMessage(
            message_id=message_id,
            author_id=user_id,
        )
        return cls(
            channel_id=channel_id,
            started_at=now,
            last_activity_at=now,
            last_gif_user_id=user_id,
            round_number=0,
            participant_ids={user_id},
            gif_messages={message_id: gif_message},
            status_message_id=None,
        )

    def add_gif_message(self, message_id: int, author_id: int) -> None:
        self.gif_messages[message_id] = GifMessage(
            message_id=message_id,
            author_id=author_id,
        )

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "started_at": self.started_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat(),
            "last_gif_user_id": self.last_gif_user_id,
            "round_number": self.round_number,
            "participant_ids": sorted(self.participant_ids),
            "gif_messages": {
                str(message_id): gif_message.to_dict()
                for message_id, gif_message in self.gif_messages.items()
            },
            "status_message_id": self.status_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BattleRound":
        return cls(
            channel_id=int(data["channel_id"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            last_activity_at=datetime.fromisoformat(data["last_activity_at"]),
            last_gif_user_id=int(data["last_gif_user_id"]),
            round_number=int(data.get("round_number", 0)),
            participant_ids={int(user_id) for user_id in data.get("participant_ids", [])},
            gif_messages={
                int(message_id): GifMessage.from_dict(gif_message_data)
                for message_id, gif_message_data in data.get("gif_messages", {}).items()
            },
            status_message_id=(
                int(data["status_message_id"])
                if data.get("status_message_id") is not None
                else None
            ),
        )


@dataclass
class UserStats:
    user_id: int
    total_points: int = 0
    total_xp: int = 0
    level: int = 1
    rounds_joined: int = 0
    rounds_won: int = 0
    current_win_streak: int = 0
    best_win_streak: int = 0

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "total_points": self.total_points,
            "total_xp": self.total_xp,
            "level": self.level,
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
            total_xp=int(data.get("total_xp", 0)),
            level=max(1, int(data.get("level", 1))),
            rounds_joined=int(data.get("rounds_joined", 0)),
            rounds_won=int(data.get("rounds_won", 0)),
            current_win_streak=int(data.get("current_win_streak", 0)),
            best_win_streak=int(data.get("best_win_streak", 0)),
        )