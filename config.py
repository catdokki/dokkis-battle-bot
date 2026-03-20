import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    battle_channel_id: int


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    channel_id_raw = os.getenv("BATTLE_CHANNEL_ID", "").strip()

    if not token:
        raise ValueError("Missing DISCORD_TOKEN in environment.")

    if not channel_id_raw:
        raise ValueError("Missing BATTLE_CHANNEL_ID in environment.")

    try:
        channel_id = int(channel_id_raw)
    except ValueError as exc:
        raise ValueError("BATTLE_CHANNEL_ID must be an integer.") from exc

    return Settings(
        discord_token=token,
        battle_channel_id=channel_id,
    )