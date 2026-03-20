from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from battle_manager import BattleManager
from config import load_settings
from gif_detector import message_contains_gif


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gif_battle_bot")

settings = load_settings()
battle_manager = BattleManager()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


def format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


async def announce_battle_winner() -> None:
    finished_round = battle_manager.end_round()
    if finished_round is None:
        return

    channel = bot.get_channel(finished_round.channel_id)
    if channel is None:
        logger.warning("Could not find battle channel %s", finished_round.channel_id)
        return

    if not isinstance(channel, discord.TextChannel):
        logger.warning("Battle channel %s is not a text channel", finished_round.channel_id)
        return

    winner_mention = f"<@{finished_round.last_gif_user_id}>"
    participant_count = len(finished_round.participant_ids)

    logger.info(
        "Battle expired | winner=%s | participants=%s",
        finished_round.last_gif_user_id,
        participant_count,
    )

    await channel.send(
        f"🏁 GIF Battle over!\n"
        f"The channel went quiet long enough.\n"
        f"Winner: {winner_mention}\n"
        f"Participants: {participant_count}"
    )


@tasks.loop(seconds=30)
async def battle_expiry_loop() -> None:
    if not battle_manager.has_active_round():
        return

    if battle_manager.is_round_expired(settings.battle_timeout_seconds):
        await announce_battle_winner()


@battle_expiry_loop.before_loop
async def before_battle_expiry_loop() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    logger.info("Watching battle channel: %s", settings.battle_channel_id)
    logger.info("Battle timeout: %s seconds", settings.battle_timeout_seconds)

    if not battle_expiry_loop.is_running():
        battle_expiry_loop.start()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.channel.id != settings.battle_channel_id:
        return

    if message_contains_gif(message):
        result = battle_manager.handle_gif_message(
            channel_id=message.channel.id,
            user_id=message.author.id,
        )

        logger.info(
            "GIF battle update | started=%s | leader=%s | participants=%s | message_id=%s",
            result.round_started,
            result.current_leader_user_id,
            result.participant_count,
            message.id,
        )

        remaining_seconds = battle_manager.get_seconds_until_timeout(
            settings.battle_timeout_seconds
        )
        remaining_text = (
            format_duration(remaining_seconds)
            if remaining_seconds is not None
            else "unknown"
        )

        if result.round_started:
            await message.channel.send(
                f"🔥 A new GIF Battle has begun!\n"
                f"Current leader: {message.author.mention}\n"
                f"Participants: {result.participant_count}\n"
                f"Timeout: {remaining_text}"
            )
        else:
            await message.channel.send(
                f"⚔️ {message.author.mention} takes the lead!\n"
                f"Participants: {result.participant_count}\n"
                f"Timeout reset: {remaining_text}"
            )

    await bot.process_commands(message)


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    await ctx.send("pong")


@bot.command(name="battle")
async def battle_status(ctx: commands.Context) -> None:
    if ctx.channel.id != settings.battle_channel_id:
        await ctx.send("This command only works in the battle channel.")
        return

    active_round = battle_manager.get_active_round()

    if active_round is None:
        await ctx.send("No active GIF Battle right now.")
        return

    leader = ctx.guild.get_member(active_round.last_gif_user_id)
    leader_name = leader.mention if leader else f"<@{active_round.last_gif_user_id}>"

    remaining_seconds = battle_manager.get_seconds_until_timeout(
        settings.battle_timeout_seconds
    )
    remaining_text = (
        format_duration(remaining_seconds)
        if remaining_seconds is not None
        else "unknown"
    )

    await ctx.send(
        f"🔥 Active GIF Battle\n"
        f"Leader: {leader_name}\n"
        f"Participants: {len(active_round.participant_ids)}\n"
        f"Time remaining: {remaining_text}"
    )


@bot.command(name="endbattle")
@commands.has_permissions(manage_guild=True)
async def end_battle(ctx: commands.Context) -> None:
    if ctx.channel.id != settings.battle_channel_id:
        await ctx.send("This command only works in the battle channel.")
        return

    finished_round = battle_manager.end_round()

    if finished_round is None:
        await ctx.send("No active battle to end.")
        return

    winner = ctx.guild.get_member(finished_round.last_gif_user_id)
    winner_name = winner.mention if winner else f"<@{finished_round.last_gif_user_id}>"

    await ctx.send(
        f"🏁 Battle ended manually.\n"
        f"Winner: {winner_name}\n"
        f"Participants: {len(finished_round.participant_ids)}"
    )


@end_battle.error
async def end_battle_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need Manage Server permission to use !endbattle.")
        return

    raise error


def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()