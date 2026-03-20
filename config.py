import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    battle_channel_id: int
    battle_timeout_seconds: int
    state_file_path: str
    user_stats_file_path: str
    champ_role_name: str
    chaos_role_name: str
    guild_id: int | None
    participation_xp: int
    win_xp: int
    streak_bonus_xp: int
    reaction_xp_per_bonus_point: int
    level_base_xp: int
    level_step_xp: int


def _get_required_int(name: str) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        raise ValueError(f"Missing {name} in environment.")
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc



def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc



def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    state_file_path = os.getenv("STATE_FILE_PATH", "data/battle_state.json").strip()
    user_stats_file_path = os.getenv("USER_STATS_FILE_PATH", "data/user_stats.json").strip()
    champ_role_name = os.getenv("CHAMP_ROLE_NAME", "GIF Battle Champ").strip()
    chaos_role_name = os.getenv("CHAOS_ROLE_NAME", "Chaos Role").strip()
    guild_id_raw = os.getenv("GUILD_ID", "").strip()

    if not token:
        raise ValueError("Missing DISCORD_TOKEN in environment.")

    channel_id = _get_required_int("BATTLE_CHANNEL_ID")
    timeout_seconds = _get_required_int("BATTLE_TIMEOUT_SECONDS")

    if timeout_seconds <= 0:
        raise ValueError("BATTLE_TIMEOUT_SECONDS must be greater than 0.")
    if not state_file_path:
        raise ValueError("STATE_FILE_PATH cannot be empty.")
    if not user_stats_file_path:
        raise ValueError("USER_STATS_FILE_PATH cannot be empty.")
    if not champ_role_name:
        raise ValueError("CHAMP_ROLE_NAME cannot be empty.")
    if not chaos_role_name:
        raise ValueError("CHAOS_ROLE_NAME cannot be empty.")

    guild_id = None
    if guild_id_raw:
        try:
            guild_id = int(guild_id_raw)
        except ValueError as exc:
            raise ValueError("GUILD_ID must be an integer.") from exc

    participation_xp = _get_int("PARTICIPATION_XP", 15)
    win_xp = _get_int("WIN_XP", 50)
    streak_bonus_xp = _get_int("STREAK_BONUS_XP", 20)
    reaction_xp_per_bonus_point = _get_int("REACTION_XP_PER_BONUS_POINT", 2)
    level_base_xp = _get_int("LEVEL_BASE_XP", 100)
    level_step_xp = _get_int("LEVEL_STEP_XP", 50)

    return Settings(
        discord_token=token,
        battle_channel_id=channel_id,
        battle_timeout_seconds=timeout_seconds,
        state_file_path=state_file_path,
        user_stats_file_path=user_stats_file_path,
        champ_role_name=champ_role_name,
        chaos_role_name=chaos_role_name,
        guild_id=guild_id,
        participation_xp=participation_xp,
        win_xp=win_xp,
        streak_bonus_xp=streak_bonus_xp,
        reaction_xp_per_bonus_point=reaction_xp_per_bonus_point,
        level_base_xp=level_base_xp,
        level_step_xp=level_step_xp,
    )
