from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from config import Settings
from points_manager import LevelConfig


@dataclass
class RuntimeConfigData:
    battle_timeout_seconds: int
    champ_role_name: str
    chaos_role_name: str
    participation_xp: int
    win_xp: int
    streak_bonus_xp: int
    reaction_xp_per_bonus_point: int
    takeover_xp: int
    level_base_xp: int
    level_step_xp: int


class RuntimeConfig:
    def __init__(self, defaults: Settings, file_path: str = "data/runtime_config.json") -> None:
        self._path = Path(file_path)
        self.data = RuntimeConfigData(
            battle_timeout_seconds=defaults.battle_timeout_seconds,
            champ_role_name=defaults.champ_role_name,
            chaos_role_name=defaults.chaos_role_name,
            participation_xp=defaults.participation_xp,
            win_xp=defaults.win_xp,
            streak_bonus_xp=defaults.streak_bonus_xp,
            reaction_xp_per_bonus_point=defaults.reaction_xp_per_bonus_point,
            takeover_xp=defaults.takeover_xp,
            level_base_xp=defaults.level_base_xp,
            level_step_xp=defaults.level_step_xp,
        )

    def load(self) -> None:
        if not self._path.exists():
            return

        raw = self._path.read_text(encoding="utf-8").strip()
        if not raw:
            return

        payload = json.loads(raw)
        merged = asdict(self.data)
        merged.update(payload)
        self.data = RuntimeConfigData(**merged)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(self.data), indent=2), encoding="utf-8")

    def update(self, key: str, value: int | str) -> None:
        if not hasattr(self.data, key):
            raise AttributeError(f"Unknown runtime config key: {key}")
        setattr(self.data, key, value)
        self.save()

    def as_level_config(self) -> LevelConfig:
        return LevelConfig(
            participation_xp=self.data.participation_xp,
            win_xp=self.data.win_xp,
            streak_bonus_xp=self.data.streak_bonus_xp,
            reaction_xp_per_bonus_point=self.data.reaction_xp_per_bonus_point,
            takeover_xp=self.data.takeover_xp,
            level_base_xp=self.data.level_base_xp,
            level_step_xp=self.data.level_step_xp,
        )