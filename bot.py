from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from battle_manager import BattleManager
from config import load_settings
from gif_detector import message_contains_gif
from points_manager import PointsManager
from storage import JsonStorage


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gif_battle_bot")

settings = load_settings()

battle_storage = JsonStorage(settings.state_file_path)
user_stats_storage = JsonStorage(settings.user_stats_file_path)

battle_manager = BattleManager(storage=battle_storage)
points_manager = PointsManager(storage=user_stats_storage)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def emoji_to_key(emoji: discord.PartialEmoji | str) -> str:
    return str(emoji)


def build_reaction_bonus_lines(
    award_summary,
    guild: discord.Guild | None,
) -> str:
    if not award_summary.reaction_bonus_by_user_id:
        return ""

    sorted_rows = sorted(
        award_summary.reaction_bonus_by_user_id.items(),
        key=lambda item: (-item[1], item[0]),
    )

    lines = ["**Crowd Favorite Bonus**"]
    for user_id, bonus in sorted_rows:
        member = guild.get_member(user_id) if guild else None
        display_name = member.mention if member else f"<@{user_id}>"
        lines.append(f"{display_name}: +{bonus}")

    return "\n".join(lines) + "\n\n"


async def announce_battle_winner() -> None:
    finished_round = battle_manager.end_round()
    if finished_round is None:
        return

    award_summary = points_manager.award_round_points(finished_round)

    channel = bot.get_channel(finished_round.channel_id)
    if channel is None:
        logger.warning("Could not find battle channel %s", finished_round.channel_id)
        return

    if not isinstance(channel, discord.TextChannel):
        logger.warning("Battle channel %s is not a text channel", finished_round.channel_id)
        return

    winner_mention = f"<@{finished_round.last_gif_user_id}>"
    participant_count = len(finished_round.participant_ids)
    winner_total = award_summary.stats_by_user_id[finished_round.last_gif_user_id].total_points
    winner_round_points = award_summary.points_awarded_by_user_id[finished_round.last_gif_user_id]

    logger.info(
        "Battle expired | winner=%s | participants=%s | winner_points_awarded=%s | streak=%s | reaction_bonus_users=%s",
        finished_round.last_gif_user_id,
        participant_count,
        winner_round_points,
        award_summary.winner_current_streak,
        len(award_summary.reaction_bonus_by_user_id),
    )

    streak_line = ""
    if award_summary.streak_bonus_awarded:
        streak_line = (
            f"🔥 Streak bonus: +5\n"
            f"Current streak: **{award_summary.winner_current_streak}** wins in a row\n\n"
        )

    reaction_lines = build_reaction_bonus_lines(award_summary, channel.guild)

    await channel.send(
        f"🏁 GIF Battle over!\n"
        f"The channel went quiet long enough.\n"
        f"Winner: {winner_mention}\n"
        f"Participants: {participant_count}\n\n"
        f"**Points awarded this round**\n"
        f"Winner earned: +{winner_round_points}\n"
        f"Everyone who joined earned: +2\n"
        f"{streak_line}"
        f"{reaction_lines}"
        f"{winner_mention} now has **{winner_total}** Chaos Points."
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
    battle_manager.load_state()
    points_manager.load_state()

    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    logger.info("Watching battle channel: %s", settings.battle_channel_id)
    logger.info("Battle timeout: %s seconds", settings.battle_timeout_seconds)
    logger.info("Battle state file: %s", settings.state_file_path)
    logger.info("User stats file: %s", settings.user_stats_file_path)

    active_round = battle_manager.get_active_round()
    if active_round is None:
        logger.info("No active round restored from disk.")
    else:
        logger.info(
            "Restored active round | leader=%s | participants=%s | gifs=%s | started_at=%s | last_activity_at=%s",
            active_round.last_gif_user_id,
            len(active_round.participant_ids),
            len(active_round.gif_messages),
            active_round.started_at.isoformat(),
            active_round.last_activity_at.isoformat(),
        )

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
            message_id=message.id,
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


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if payload.channel_id != settings.battle_channel_id:
        return

    if payload.user_id == bot.user.id if bot.user else False:
        return

    changed = battle_manager.record_reaction_add(
        message_id=payload.message_id,
        reactor_user_id=payload.user_id,
        emoji_key=emoji_to_key(payload.emoji),
    )

    if changed:
        logger.info(
            "Reaction tracked | message_id=%s | user_id=%s | emoji=%s",
            payload.message_id,
            payload.user_id,
            emoji_to_key(payload.emoji),
        )


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    if payload.channel_id != settings.battle_channel_id:
        return

    changed = battle_manager.record_reaction_remove(
        message_id=payload.message_id,
        reactor_user_id=payload.user_id,
        emoji_key=emoji_to_key(payload.emoji),
    )

    if changed:
        logger.info(
            "Reaction removed | message_id=%s | user_id=%s | emoji=%s",
            payload.message_id,
            payload.user_id,
            emoji_to_key(payload.emoji),
        )


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
        f"GIFs this round: {len(active_round.gif_messages)}\n"
        f"Time remaining: {remaining_text}"
    )


@bot.command(name="points")
async def points(ctx: commands.Context, member: discord.Member | None = None) -> None:
    target = member or ctx.author
    stats = points_manager.get_user_stats(target.id)

    await ctx.send(
        f"📊 Stats for {target.mention}\n"
        f"Chaos Points: **{stats.total_points}**\n"
        f"Rounds Joined: **{stats.rounds_joined}**\n"
        f"Rounds Won: **{stats.rounds_won}**\n"
        f"Current Win Streak: **{stats.current_win_streak}**\n"
        f"Best Win Streak: **{stats.best_win_streak}**"
    )


@bot.command(name="leaderboard")
async def leaderboard(ctx: commands.Context) -> None:
    leaderboard_rows = points_manager.get_leaderboard(limit=10)

    if not leaderboard_rows:
        await ctx.send("No Chaos Points yet. Start a battle.")
        return

    lines = []
    for index, stats in enumerate(leaderboard_rows, start=1):
        member = ctx.guild.get_member(stats.user_id)
        display_name = member.mention if member else f"<@{stats.user_id}>"
        lines.append(
            f"{index}. {display_name} — {stats.total_points} pts "
            f"(wins: {stats.rounds_won}, streak: {stats.current_win_streak}, best: {stats.best_win_streak})"
        )

    await ctx.send("🏆 Chaos Leaderboard\n" + "\n".join(lines))


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

    award_summary = points_manager.award_round_points(finished_round)

    winner = ctx.guild.get_member(finished_round.last_gif_user_id)
    winner_name = winner.mention if winner else f"<@{finished_round.last_gif_user_id}>"
    winner_total = award_summary.stats_by_user_id[finished_round.last_gif_user_id].total_points
    winner_round_points = award_summary.points_awarded_by_user_id[finished_round.last_gif_user_id]

    streak_line = ""
    if award_summary.streak_bonus_awarded:
        streak_line = (
            f"\n🔥 Streak bonus: +5"
            f"\nCurrent streak: **{award_summary.winner_current_streak}**"
        )

    reaction_lines = ""
    if award_summary.reaction_bonus_by_user_id:
        reaction_lines = "\n" + build_reaction_bonus_lines(award_summary, ctx.guild).rstrip()

    await ctx.send(
        f"🏁 Battle ended manually.\n"
        f"Winner: {winner_name}\n"
        f"Participants: {len(finished_round.participant_ids)}\n"
        f"Winner earned: +{winner_round_points}\n"
        f"{winner_name} now has **{winner_total}** Chaos Points."
        f"{streak_line}"
        f"{reaction_lines}"
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