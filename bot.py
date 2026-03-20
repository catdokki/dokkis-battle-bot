from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import load_settings
from gif_detector import message_contains_gif


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gif_battle_bot")

settings = load_settings()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    logger.info("Watching battle channel: %s", settings.battle_channel_id)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.channel.id != settings.battle_channel_id:
        return

    if message_contains_gif(message):
        logger.info(
            "GIF detected | user=%s | channel=%s | message_id=%s",
            message.author,
            message.channel.id,
            message.id,
        )
        await message.channel.send(
            f"GIF detected from {message.author.mention} — battle logic comes next."
        )

    await bot.process_commands(message)


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    await ctx.send("pong")


def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()