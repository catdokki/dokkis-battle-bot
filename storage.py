from __future__ import annotations

import json
from pathlib import Path

from models import BattleRound


class JsonStorage:
    def __init__(self, file_path: str) -> None:
        self.file_path = Path(file_path)

    def ensure_parent_dir(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def save_active_round(self, battle_round: BattleRound | None) -> None:
        self.ensure_parent_dir()

        payload = {
            "active_round": battle_round.to_dict() if battle_round is not None else None,
        }

        self.file_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def load_active_round(self) -> BattleRound | None:
        if not self.file_path.exists():
            return None

        raw_text = self.file_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return None

        payload = json.loads(raw_text)
        active_round_data = payload.get("active_round")

        if active_round_data is None:
            return None

        return BattleRound.from_dict(active_round_data)