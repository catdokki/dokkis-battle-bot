from __future__ import annotations

import json
from pathlib import Path

from models import BattleRound, UserStats


class JsonStorage:
    def __init__(self, file_path: str) -> None:
        self.file_path = Path(file_path)

    def ensure_parent_dir(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def write_json(self, payload: dict) -> None:
        self.ensure_parent_dir()
        self.file_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def read_json(self) -> dict | None:
        if not self.file_path.exists():
            return None

        raw_text = self.file_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return None

        return json.loads(raw_text)

    def save_active_round(self, battle_round: BattleRound | None) -> None:
        payload = {
            "active_round": battle_round.to_dict() if battle_round is not None else None,
        }
        self.write_json(payload)

    def load_active_round(self) -> BattleRound | None:
        payload = self.read_json()
        if not payload:
            return None

        active_round_data = payload.get("active_round")
        if active_round_data is None:
            return None

        return BattleRound.from_dict(active_round_data)

    def save_user_stats(self, stats_by_user_id: dict[int, UserStats]) -> None:
        payload = {
            "users": {
                str(user_id): stats.to_dict()
                for user_id, stats in stats_by_user_id.items()
            }
        }
        self.write_json(payload)

    def load_user_stats(self) -> dict[int, UserStats]:
        payload = self.read_json()
        if not payload:
            return {}

        users_data = payload.get("users", {})
        results: dict[int, UserStats] = {}

        for user_id_str, stats_data in users_data.items():
            stats = UserStats.from_dict(stats_data)
            results[int(user_id_str)] = stats

        return results