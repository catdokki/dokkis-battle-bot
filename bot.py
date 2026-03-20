from __future__ import annotations

import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from battle_manager import BattleManager
from config import load_settings
from gif_detector import message_contains_gif
from points_manager import LevelConfig, PointsManager
from role_manager import RoleManager
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
points_manager = PointsManager(
    storage=user_stats_storage,
    level_config=LevelConfig(
        participation_xp=settings.participation_xp,
        win_xp=settings.win_xp,
        streak_bonus_xp=settings.streak_bonus_xp,
        reaction_xp_per_bonus_point=settings.reaction_xp_per_bonus_point,
        level_base_xp=settings.level_base_xp,
        level_step_xp=settings.level_step_xp,
    ),
)
role_manager = RoleManager(champ_role_name=settings.champ_role_name)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def format_discord_relative_time(target_time: datetime) -> str:
    return f"<t:{int(target_time.timestamp())}:R>"


def format_discord_full_time(target_time: datetime) -> str:
    return f"<t:{int(target_time.timestamp())}:F>"


def emoji_to_key(emoji: discord.PartialEmoji | str) -> str:
    return str(emoji)


def build_battle_status_text(*, guild: discord.Guild | None, active_round, timeout_seconds: int) -> str:
    leader_user_id = active_round.last_gif_user_id
    leader = guild.get_member(leader_user_id) if guild else None
    leader_name = leader.mention if leader else f"<@{leader_user_id}>"
    deadline = active_round.last_activity_at + timedelta(seconds=timeout_seconds)

    return (
        "🔥 **GIF Battle Active**\n"
        f"Leader: {leader_name}\n"
        f"Participants: {len(active_round.participant_ids)}\n"
        f"GIFs this round: {len(active_round.gif_messages)}\n"
        f"Battle naps {format_discord_relative_time(deadline)}\n"
        f"Deadline: {format_discord_full_time(deadline)}"
    )


def build_reaction_bonus_lines(award_summary, guild: discord.Guild | None) -> str:
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
        xp_bonus = award_summary.xp_awarded_by_user_id.get(user_id, 0)
        lines.append(f"{display_name}: +{bonus} points, +{xp_bonus} XP")

    return "\n".join(lines) + "\n\n"


def build_level_up_lines(award_summary, guild: discord.Guild | None) -> str:
    if not award_summary.level_ups_by_user_id:
        return ""

    lines = ["**Level Ups**"]
    for user_id, levels_gained in sorted(award_summary.level_ups_by_user_id.items()):
        member = guild.get_member(user_id) if guild else None
        display_name = member.mention if member else f"<@{user_id}>"
        new_level = award_summary.stats_by_user_id[user_id].level
        if levels_gained == 1:
            lines.append(f"{display_name} reached **Level {new_level}**")
        else:
            lines.append(f"{display_name} jumped +{levels_gained} levels to **Level {new_level}**")

    return "\n".join(lines) + "\n\n"


def build_profile_text(member: discord.Member, *, include_title: bool = True) -> str:
    stats = points_manager.get_user_stats(member.id)
    progress = points_manager.get_level_progress(member.id)
    header = f"📊 Stats for {member.mention}\n" if include_title else ""
    return (
        f"{header}"
        f"Chaos Points: **{stats.total_points}**\n"
        f"Level: **{progress.level}**\n"
        f"XP: **{progress.total_xp}** total\n"
        f"Progress to next level: **{progress.xp_into_level}/{progress.xp_needed_for_next_level} XP** ({progress.progress_percent:.1f}%)\n"
        f"Rounds Joined: **{stats.rounds_joined}**\n"
        f"Rounds Won: **{stats.rounds_won}**\n"
        f"Current Win Streak: **{stats.current_win_streak}**\n"
        f"Best Win Streak: **{stats.best_win_streak}**"
    )


async def user_has_chaos_role(member: discord.Member) -> bool:
    return discord.utils.get(member.roles, name=settings.chaos_role_name) is not None


async def ensure_chaos_access_for_context(ctx: commands.Context) -> bool:
    if not isinstance(ctx.author, discord.Member):
        return False
    return await user_has_chaos_role(ctx.author)


async def ensure_chaos_access_for_interaction(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return await user_has_chaos_role(interaction.user)


async def send_chaos_role_required_response(target) -> None:
    message = f"You need the **{settings.chaos_role_name}** role to use battle commands."
    if isinstance(target, commands.Context):
        await target.send(message)
        return

    if target.response.is_done():
        await target.followup.send(message, ephemeral=True)
    else:
        await target.response.send_message(message, ephemeral=True)


async def upsert_battle_status_message(channel: discord.TextChannel) -> None:
    active_round = battle_manager.get_active_round()
    if active_round is None:
        return

    content = build_battle_status_text(
        guild=channel.guild,
        active_round=active_round,
        timeout_seconds=settings.battle_timeout_seconds,
    )

    status_message_id = battle_manager.get_status_message_id()
    if status_message_id is not None:
        try:
            existing_message = await channel.fetch_message(status_message_id)
            await existing_message.edit(content=content)
            return
        except discord.NotFound:
            logger.info("Tracked battle status message %s no longer exists.", status_message_id)
        except discord.Forbidden:
            logger.warning("Missing permission to edit battle status message %s.", status_message_id)
        except discord.HTTPException as exc:
            logger.warning("Failed to edit battle status message %s: %s", status_message_id, exc)

    new_message = await channel.send(content)
    battle_manager.set_status_message_id(new_message.id)


async def clear_battle_status_message(channel: discord.TextChannel, status_message_id: int | None) -> None:
    if status_message_id is None:
        return
    try:
        message = await channel.fetch_message(status_message_id)
        await message.edit(content="✅ This battle has ended.")
    except discord.NotFound:
        return
    except discord.Forbidden:
        logger.warning("Missing permission to edit ended battle status message %s.", status_message_id)
    except discord.HTTPException as exc:
        logger.warning("Failed to edit ended battle status message %s: %s", status_message_id, exc)


async def sync_commands() -> None:
    try:
        if settings.guild_id is not None:
            guild_object = discord.Object(id=settings.guild_id)
            bot.tree.copy_global_to(guild=guild_object)
            synced = await bot.tree.sync(guild=guild_object)
            logger.info("Synced %s app commands to guild %s", len(synced), settings.guild_id)
        else:
            synced = await bot.tree.sync()
            logger.info("Synced %s global app commands", len(synced))
    except discord.HTTPException as exc:
        logger.warning("Failed to sync app commands: %s", exc)


async def announce_battle_winner() -> None:
    active_round = battle_manager.get_active_round()
    if active_round is None:
        return

    status_message_id = active_round.status_message_id
    finished_round = battle_manager.end_round()
    if finished_round is None:
        return

    award_summary = points_manager.award_round_points(finished_round)
    channel = bot.get_channel(finished_round.channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        logger.warning("Could not find battle text channel %s", finished_round.channel_id)
        return

    await clear_battle_status_message(channel, status_message_id)
    await role_manager.assign_champ_role(channel.guild, finished_round.last_gif_user_id)

    winner_mention = f"<@{finished_round.last_gif_user_id}>"
    participant_count = len(finished_round.participant_ids)
    winner_total = award_summary.stats_by_user_id[finished_round.last_gif_user_id].total_points
    winner_round_points = award_summary.points_awarded_by_user_id[finished_round.last_gif_user_id]
    winner_round_xp = award_summary.xp_awarded_by_user_id.get(finished_round.last_gif_user_id, 0)
    winner_level = award_summary.stats_by_user_id[finished_round.last_gif_user_id].level

    streak_line = ""
    if award_summary.streak_bonus_awarded:
        streak_line = (
            "🔥 Streak bonus: +5 points\n"
            f"Current streak: **{award_summary.winner_current_streak}** wins in a row\n\n"
        )

    reaction_lines = build_reaction_bonus_lines(award_summary, channel.guild)
    level_up_lines = build_level_up_lines(award_summary, channel.guild)

    await channel.send(
        "🏁 GIF Battle over!\n"
        "The channel went quiet long enough.\n"
        f"Winner: {winner_mention}\n"
        f"Participants: {participant_count}\n\n"
        "**Rewards this round**\n"
        f"Winner earned: +{winner_round_points} points, +{winner_round_xp} XP\n"
        f"Everyone who joined earned: +2 points, +{settings.participation_xp} XP\n"
        f"{streak_line}"
        f"{reaction_lines}"
        f"{level_up_lines}"
        f"{winner_mention} now has **{winner_total}** Chaos Points and is **Level {winner_level}**."
    )


@tasks.loop(seconds=30)
async def battle_expiry_loop() -> None:
    if battle_manager.has_active_round() and battle_manager.is_round_expired(settings.battle_timeout_seconds):
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
    logger.info("Champ role name: %s", settings.champ_role_name)
    logger.info("Chaos role name: %s", settings.chaos_role_name)

    if not battle_expiry_loop.is_running():
        battle_expiry_loop.start()

    await sync_commands()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.channel.id == settings.battle_channel_id and message_contains_gif(message):
        result = battle_manager.handle_gif_message(
            channel_id=message.channel.id,
            user_id=message.author.id,
            message_id=message.id,
        )
        logger.info(
            "GIF battle update | started=%s | leader_changed=%s | timeout_reset=%s | leader=%s | participants=%s | message_id=%s",
            result.round_started,
            result.leader_changed,
            result.timeout_reset,
            result.current_leader_user_id,
            result.participant_count,
            message.id,
        )
        if isinstance(message.channel, discord.TextChannel):
            await upsert_battle_status_message(message.channel)

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
        logger.info("Reaction tracked | message_id=%s | user_id=%s | emoji=%s", payload.message_id, payload.user_id, emoji_to_key(payload.emoji))


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
        logger.info("Reaction removed | message_id=%s | user_id=%s | emoji=%s", payload.message_id, payload.user_id, emoji_to_key(payload.emoji))


@bot.check
async def global_chaos_role_check(ctx: commands.Context) -> bool:
    if ctx.command is None:
        return True
    allowed = await ensure_chaos_access_for_context(ctx)
    if not allowed:
        await send_chaos_role_required_response(ctx)
    return allowed


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.CheckFailure):
        await send_chaos_role_required_response(interaction)
        return
    raise error


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="battle", description="Show the current GIF battle status.")
async def battle_status_slash(interaction: discord.Interaction) -> None:
    if interaction.channel_id != settings.battle_channel_id:
        await interaction.response.send_message("This command only works in the battle channel.", ephemeral=True)
        return

    active_round = battle_manager.get_active_round()
    if active_round is None:
        await interaction.response.send_message("No active GIF Battle right now.", ephemeral=True)
        return

    await interaction.response.send_message(
        build_battle_status_text(
            guild=interaction.guild,
            active_round=active_round,
            timeout_seconds=settings.battle_timeout_seconds,
        )
    )


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="profile", description="Show Chaos Points, XP, level, and streak stats.")
@app_commands.describe(member="Optional member to inspect")
async def profile_slash(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    target = member or interaction.user
    assert isinstance(target, discord.Member)
    await interaction.response.send_message(build_profile_text(target))


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="leaderboard", description="Show the top Chaos leaderboard.")
async def leaderboard_slash(interaction: discord.Interaction) -> None:
    leaderboard_rows = points_manager.get_leaderboard(limit=10)
    if not leaderboard_rows:
        await interaction.response.send_message("No Chaos Points yet. Start a battle.")
        return

    lines = []
    guild = interaction.guild
    for index, stats in enumerate(leaderboard_rows, start=1):
        member = guild.get_member(stats.user_id) if guild else None
        display_name = member.mention if member else f"<@{stats.user_id}>"
        lines.append(
            f"{index}. {display_name} — Level {stats.level}, {stats.total_xp} XP, {stats.total_points} pts "
            f"(wins: {stats.rounds_won}, streak: {stats.current_win_streak}, best: {stats.best_win_streak})"
        )

    await interaction.response.send_message("🏆 Chaos Leaderboard\n" + "\n".join(lines))


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="champ", description="Show the current GIF Battle Champ.")
async def champ_slash(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    role = discord.utils.get(guild.roles, name=settings.champ_role_name)
    if role is None or not role.members:
        await interaction.response.send_message(f"No current **{settings.champ_role_name}** yet.")
        return

    await interaction.response.send_message(f"👑 Current **{role.name}**: {role.members[0].mention}")


@app_commands.check(ensure_chaos_access_for_interaction)
@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="endbattle", description="Manually end the active GIF battle.")
async def endbattle_slash(interaction: discord.Interaction) -> None:
    if interaction.channel_id != settings.battle_channel_id:
        await interaction.response.send_message("This command only works in the battle channel.", ephemeral=True)
        return

    active_round = battle_manager.get_active_round()
    if active_round is None:
        await interaction.response.send_message("No active battle to end.", ephemeral=True)
        return

    status_message_id = active_round.status_message_id
    finished_round = battle_manager.end_round()
    if finished_round is None:
        await interaction.response.send_message("No active battle to end.", ephemeral=True)
        return

    channel = interaction.channel
    if isinstance(channel, discord.TextChannel):
        await clear_battle_status_message(channel, status_message_id)

    award_summary = points_manager.award_round_points(finished_round)
    if interaction.guild:
        await role_manager.assign_champ_role(interaction.guild, finished_round.last_gif_user_id)

    winner_name = f"<@{finished_round.last_gif_user_id}>"
    winner_total = award_summary.stats_by_user_id[finished_round.last_gif_user_id].total_points
    winner_level = award_summary.stats_by_user_id[finished_round.last_gif_user_id].level
    winner_points = award_summary.points_awarded_by_user_id[finished_round.last_gif_user_id]
    winner_xp = award_summary.xp_awarded_by_user_id.get(finished_round.last_gif_user_id, 0)

    await interaction.response.send_message(
        "🏁 Battle ended manually.\n"
        f"Winner: {winner_name}\n"
        f"Participants: {len(finished_round.participant_ids)}\n"
        f"Winner earned: +{winner_points} points, +{winner_xp} XP\n"
        f"{winner_name} now has **{winner_total}** Chaos Points and is **Level {winner_level}**."
    )


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    await ctx.send("pong")


@bot.command(name="battle")
async def battle_status_prefix(ctx: commands.Context) -> None:
    if ctx.channel.id != settings.battle_channel_id:
        await ctx.send("This command only works in the battle channel.")
        return

    active_round = battle_manager.get_active_round()
    if active_round is None:
        await ctx.send("No active GIF Battle right now.")
        return

    await ctx.send(build_battle_status_text(guild=ctx.guild, active_round=active_round, timeout_seconds=settings.battle_timeout_seconds))


@bot.command(name="points", aliases=["profile"])
async def points_prefix(ctx: commands.Context, member: discord.Member | None = None) -> None:
    target = member or ctx.author
    assert isinstance(target, discord.Member)
    await ctx.send(build_profile_text(target))


@bot.command(name="leaderboard")
async def leaderboard_prefix(ctx: commands.Context) -> None:
    leaderboard_rows = points_manager.get_leaderboard(limit=10)
    if not leaderboard_rows:
        await ctx.send("No Chaos Points yet. Start a battle.")
        return

    lines = []
    for index, stats in enumerate(leaderboard_rows, start=1):
        member = ctx.guild.get_member(stats.user_id) if ctx.guild else None
        display_name = member.mention if member else f"<@{stats.user_id}>"
        lines.append(
            f"{index}. {display_name} — Level {stats.level}, {stats.total_xp} XP, {stats.total_points} pts "
            f"(wins: {stats.rounds_won}, streak: {stats.current_win_streak}, best: {stats.best_win_streak})"
        )

    await ctx.send("🏆 Chaos Leaderboard\n" + "\n".join(lines))


@bot.command(name="champ")
async def champ_prefix(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("This command only works in a server.")
        return

    role = discord.utils.get(ctx.guild.roles, name=settings.champ_role_name)
    if role is None or not role.members:
        await ctx.send(f"No current **{settings.champ_role_name}** yet.")
        return

    await ctx.send(f"👑 Current **{role.name}**: {role.members[0].mention}")


@bot.command(name="endbattle")
@commands.has_permissions(manage_guild=True)
async def endbattle_prefix(ctx: commands.Context) -> None:
    if ctx.channel.id != settings.battle_channel_id:
        await ctx.send("This command only works in the battle channel.")
        return

    active_round = battle_manager.get_active_round()
    if active_round is None:
        await ctx.send("No active battle to end.")
        return

    status_message_id = active_round.status_message_id
    finished_round = battle_manager.end_round()
    if finished_round is None:
        await ctx.send("No active battle to end.")
        return

    if isinstance(ctx.channel, discord.TextChannel):
        await clear_battle_status_message(ctx.channel, status_message_id)
    if ctx.guild:
        await role_manager.assign_champ_role(ctx.guild, finished_round.last_gif_user_id)

    award_summary = points_manager.award_round_points(finished_round)
    winner_name = f"<@{finished_round.last_gif_user_id}>"
    winner_total = award_summary.stats_by_user_id[finished_round.last_gif_user_id].total_points
    winner_level = award_summary.stats_by_user_id[finished_round.last_gif_user_id].level
    winner_points = award_summary.points_awarded_by_user_id[finished_round.last_gif_user_id]
    winner_xp = award_summary.xp_awarded_by_user_id.get(finished_round.last_gif_user_id, 0)

    await ctx.send(
        "🏁 Battle ended manually.\n"
        f"Winner: {winner_name}\n"
        f"Participants: {len(finished_round.participant_ids)}\n"
        f"Winner earned: +{winner_points} points, +{winner_xp} XP\n"
        f"{winner_name} now has **{winner_total}** Chaos Points and is **Level {winner_level}**."
    )


@endbattle_prefix.error
async def endbattle_prefix_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need Manage Server permission to use !endbattle.")
        return
    raise error


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="pingbattle", description="Check whether the bot is alive.")
async def ping_slash(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("pong", ephemeral=True)



def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
