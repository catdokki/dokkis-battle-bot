import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    battle_channel_id: int
    battle_timeout_seconds: int


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    channel_id_raw = os.getenv("BATTLE_CHANNEL_ID", "").strip()
    timeout_raw = os.getenv("BATTLE_TIMEOUT_SECONDS", "").strip()

    if not token:
        raise ValueError("Missing DISCORD_TOKEN in environment.")

    if not channel_id_raw:
        raise ValueError("Missing BATTLE_CHANNEL_ID in environment.")

    if not timeout_raw:
        raise ValueError("Missing BATTLE_TIMEOUT_SECONDS in environment.")

    try:
        channel_id = int(channel_id_raw)
    except ValueError as exc:
        raise ValueError("BATTLE_CHANNEL_ID must be an integer.") from exc

    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise ValueError("BATTLE_TIMEOUT_SECONDS must be an integer.") from exc

    if timeout_seconds <= 0:
        raise ValueError("BATTLE_TIMEOUT_SECONDS must be greater than 0.")

    return Settings(
        discord_token=token,
        battle_channel_id=channel_id,
        battle_timeout_seconds=timeout_seconds,
    )