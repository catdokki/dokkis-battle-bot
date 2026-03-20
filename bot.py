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
from runtime_config import RuntimeConfig
from storage import JsonStorage


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gif_battle_bot")
settings = load_settings()
runtime_config = RuntimeConfig(settings)

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


def current_timeout_seconds() -> int:
    return runtime_config.data.battle_timeout_seconds


def current_chaos_role_name() -> str:
    return runtime_config.data.chaos_role_name


def current_champ_role_name() -> str:
    return runtime_config.data.champ_role_name


def apply_runtime_config() -> None:
    role_manager.champ_role_name = current_champ_role_name()
    points_manager.update_level_config(runtime_config.as_level_config())


def format_discord_relative_time(target_time: datetime) -> str:
    return f"<t:{int(target_time.timestamp())}:R>"


def format_discord_full_time(target_time: datetime) -> str:
    return f"<t:{int(target_time.timestamp())}:F>"


def emoji_to_key(emoji: discord.PartialEmoji | str) -> str:
    return str(emoji)


def level_meter(progress_percent: float, *, width: int = 10) -> str:
    filled = max(0, min(width, round((progress_percent / 100) * width)))
    return "█" * filled + "░" * (width - filled)


def make_embed(title: str, description: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_battle_status_embed(*, guild: discord.Guild | None, active_round, timeout_seconds: int) -> discord.Embed:
    leader_user_id = active_round.last_gif_user_id
    leader = guild.get_member(leader_user_id) if guild else None
    leader_name = leader.mention if leader else f"<@{leader_user_id}>"
    deadline = active_round.last_activity_at + timedelta(seconds=timeout_seconds)
    started_line = format_discord_full_time(active_round.started_at)
    embed = make_embed("🔥 GIF Battle Active", "The round stays alive until a different battler posts the next GIF.")
    embed.add_field(name="Current Leader", value=leader_name, inline=True)
    embed.add_field(name="Participants", value=str(len(active_round.participant_ids)), inline=True)
    embed.add_field(name="GIFs", value=str(len(active_round.gif_messages)), inline=True)
    embed.add_field(name="Started", value=started_line, inline=False)
    embed.add_field(name="Battle naps", value=format_discord_relative_time(deadline), inline=True)
    embed.add_field(name="Deadline", value=format_discord_full_time(deadline), inline=True)
    return embed


def build_profile_embed(member: discord.Member) -> discord.Embed:
    stats = points_manager.get_user_stats(member.id)
    progress = points_manager.get_level_progress(member.id)
    meter = level_meter(progress.progress_percent)
    embed = make_embed(f"📊 {member.display_name}'s Chaos Profile", member.mention)
    embed.add_field(name="Chaos Points", value=f"**{stats.total_points}**", inline=True)
    embed.add_field(name="Level", value=f"**{progress.level}**", inline=True)
    embed.add_field(name="Total XP", value=f"**{progress.total_xp}**", inline=True)
    embed.add_field(
        name="Level Progress",
        value=(
            f"`{meter}`\n"
            f"{progress.xp_into_level}/{progress.xp_needed_for_next_level} XP to next level\n"
            f"{progress.progress_percent:.1f}% complete"
        ),
        inline=False,
    )
    embed.add_field(name="Rounds Joined", value=str(stats.rounds_joined), inline=True)
    embed.add_field(name="Rounds Won", value=str(stats.rounds_won), inline=True)
    embed.add_field(name="Current Streak", value=str(stats.current_win_streak), inline=True)
    embed.add_field(name="Best Streak", value=str(stats.best_win_streak), inline=True)
    return embed


def build_leaderboard_embed(guild: discord.Guild | None) -> discord.Embed:
    leaderboard_rows = points_manager.get_leaderboard(limit=10)
    embed = make_embed("🏆 Chaos Leaderboard", "Top battlers by level, XP, and Chaos Points.")
    if not leaderboard_rows:
        embed.description = "No Chaos Points yet. Start a battle."
        return embed

    lines: list[str] = []
    for index, stats in enumerate(leaderboard_rows, start=1):
        member = guild.get_member(stats.user_id) if guild else None
        display_name = member.mention if member else f"<@{stats.user_id}>"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"`#{index}`")
        lines.append(
            f"{medal} {display_name} — **Lvl {stats.level}** · {stats.total_xp} XP · {stats.total_points} pts · "
            f"{stats.rounds_won} wins · streak {stats.current_win_streak}"
        )
    embed.description = "\n".join(lines)
    return embed


def build_champ_embed(guild: discord.Guild) -> discord.Embed:
    role = discord.utils.get(guild.roles, name=current_champ_role_name())
    if role is None or not role.members:
        return make_embed("👑 GIF Battle Champ", f"No current **{current_champ_role_name()}** yet.")

    winner = role.members[0]
    embed = make_embed("👑 GIF Battle Champ", f"Current champ: {winner.mention}")
    embed.add_field(name="Role", value=role.name, inline=True)
    embed.add_field(name="Holder", value=winner.display_name, inline=True)
    return embed


def build_admin_config_embed() -> discord.Embed:
    data = runtime_config.data
    embed = make_embed("🛠️ GIF Battle Config", "Live runtime settings saved by the bot.")
    embed.add_field(name="Battle Timeout", value=f"{data.battle_timeout_seconds} sec", inline=True)
    embed.add_field(name="Chaos Role", value=data.chaos_role_name, inline=True)
    embed.add_field(name="Champ Role", value=data.champ_role_name, inline=True)
    embed.add_field(name="Participation XP", value=str(data.participation_xp), inline=True)
    embed.add_field(name="Win XP", value=str(data.win_xp), inline=True)
    embed.add_field(name="Streak Bonus XP", value=str(data.streak_bonus_xp), inline=True)
    embed.add_field(name="Reaction XP / Point", value=str(data.reaction_xp_per_bonus_point), inline=True)
    embed.add_field(name="Level Base XP", value=str(data.level_base_xp), inline=True)
    embed.add_field(name="Level Step XP", value=str(data.level_step_xp), inline=True)
    return embed


def build_round_summary_embed(
    finished_round,
    award_summary,
    *,
    guild: discord.Guild | None,
    manual_end: bool,
) -> discord.Embed:
    winner_user_id = finished_round.last_gif_user_id
    winner_mention = f"<@{winner_user_id}>"
    winner_stats = award_summary.stats_by_user_id[winner_user_id]
    winner_progress = award_summary.level_progress_by_user_id[winner_user_id]
    meter = level_meter(winner_progress.progress_percent)
    title = "🏁 GIF Battle Closed" if not manual_end else "🛑 GIF Battle Ended by Admin"
    subtitle = "The channel went quiet long enough. Last GIF standing takes it." if not manual_end else "An admin closed the round and locked in the current leader."
    embed = make_embed(title, subtitle)
    embed.add_field(name="Winner", value=winner_mention, inline=True)
    embed.add_field(name="Participants", value=str(len(finished_round.participant_ids)), inline=True)
    embed.add_field(name="GIFs Posted", value=str(len(finished_round.gif_messages)), inline=True)

    winner_points = award_summary.points_awarded_by_user_id[winner_user_id]
    winner_xp = award_summary.xp_awarded_by_user_id.get(winner_user_id, 0)
    rewards_lines = [
        f"Winner: **+{winner_points} points** · **+{winner_xp} XP**",
        f"Everyone who joined: **+2 points** · **+{runtime_config.data.participation_xp} XP**",
    ]
    if award_summary.streak_bonus_awarded:
        rewards_lines.append(f"Streak bonus live: **{award_summary.winner_current_streak} wins in a row**")
    embed.add_field(name="Round Rewards", value="\n".join(rewards_lines), inline=False)

    if award_summary.reaction_bonus_by_user_id:
        reaction_lines = []
        sorted_rows = sorted(award_summary.reaction_bonus_by_user_id.items(), key=lambda item: (-item[1], item[0]))
        for user_id, bonus in sorted_rows[:6]:
            member = guild.get_member(user_id) if guild else None
            display_name = member.mention if member else f"<@{user_id}>"
            xp_total = award_summary.xp_awarded_by_user_id.get(user_id, 0)
            reaction_lines.append(f"{display_name}: +{bonus} pts · +{xp_total} XP total")
        embed.add_field(name="Crowd Favorite", value="\n".join(reaction_lines), inline=False)

    if award_summary.level_ups_by_user_id:
        level_lines = []
        for user_id, levels_gained in sorted(award_summary.level_ups_by_user_id.items(), key=lambda item: item[0]):
            member = guild.get_member(user_id) if guild else None
            display_name = member.mention if member else f"<@{user_id}>"
            new_level = award_summary.stats_by_user_id[user_id].level
            level_lines.append(f"{display_name}: +{levels_gained} level{'s' if levels_gained != 1 else ''} → **{new_level}**")
        embed.add_field(name="Level Ups", value="\n".join(level_lines), inline=False)

    embed.add_field(
        name="Winner Progress",
        value=(
            f"Level **{winner_stats.level}** · {winner_stats.total_points} total points\n"
            f"`{meter}`\n"
            f"{winner_progress.xp_into_level}/{winner_progress.xp_needed_for_next_level} XP"
        ),
        inline=False,
    )
    return embed


async def user_has_chaos_role(member: discord.Member) -> bool:
    return discord.utils.get(member.roles, name=current_chaos_role_name()) is not None


async def ensure_chaos_access_for_context(ctx: commands.Context) -> bool:
    if not isinstance(ctx.author, discord.Member):
        return False
    return await user_has_chaos_role(ctx.author)


async def ensure_chaos_access_for_interaction(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return await user_has_chaos_role(interaction.user)


async def send_chaos_role_required_response(target) -> None:
    message = f"You need the **{current_chaos_role_name()}** role to use battle commands."
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

    embed = build_battle_status_embed(
        guild=channel.guild,
        active_round=active_round,
        timeout_seconds=current_timeout_seconds(),
    )

    status_message_id = battle_manager.get_status_message_id()
    if status_message_id is not None:
        try:
            existing_message = await channel.fetch_message(status_message_id)
            await existing_message.edit(content=None, embed=embed)
            return
        except discord.NotFound:
            logger.info("Tracked battle status message %s no longer exists.", status_message_id)
        except discord.Forbidden:
            logger.warning("Missing permission to edit battle status message %s.", status_message_id)
        except discord.HTTPException as exc:
            logger.warning("Failed to edit battle status message %s: %s", status_message_id, exc)

    new_message = await channel.send(embed=embed)
    battle_manager.set_status_message_id(new_message.id)


async def clear_battle_status_message(channel: discord.TextChannel, status_message_id: int | None) -> None:
    if status_message_id is None:
        return
    try:
        message = await channel.fetch_message(status_message_id)
        embed = make_embed("✅ Battle Closed", "This status card is now archived.")
        await message.edit(content=None, embed=embed)
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

            # Copy globally-declared commands into the guild command tree
            # so they appear immediately in this server.
            bot.tree.copy_global_to(guild=guild_object)

            synced = await bot.tree.sync(guild=guild_object)
            logger.info("Synced %s app commands to guild %s", len(synced), settings.guild_id)
        else:
            synced = await bot.tree.sync()
            logger.info("Synced %s global app commands", len(synced))
    except discord.HTTPException as exc:
        logger.warning("Failed to sync app commands: %s", exc)


async def finalize_battle_round(*, finished_round, guild: discord.Guild | None, manual_end: bool) -> discord.Embed:
    award_summary = points_manager.award_round_points(finished_round)
    if guild is not None:
        await role_manager.assign_champ_role(guild, finished_round.last_gif_user_id)
    return build_round_summary_embed(finished_round, award_summary, guild=guild, manual_end=manual_end)


async def announce_battle_winner() -> None:
    active_round = battle_manager.get_active_round()
    if active_round is None:
        return

    status_message_id = active_round.status_message_id
    finished_round = battle_manager.end_round()
    if finished_round is None:
        return

    channel = bot.get_channel(finished_round.channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        logger.warning("Could not find battle text channel %s", finished_round.channel_id)
        return

    await clear_battle_status_message(channel, status_message_id)
    summary_embed = await finalize_battle_round(finished_round=finished_round, guild=channel.guild, manual_end=False)
    await channel.send(embed=summary_embed)


@tasks.loop(seconds=30)
async def battle_expiry_loop() -> None:
    if battle_manager.has_active_round() and battle_manager.is_round_expired(current_timeout_seconds()):
        await announce_battle_winner()
    else:
        channel = bot.get_channel(settings.battle_channel_id)
        if isinstance(channel, discord.TextChannel) and battle_manager.has_active_round():
            await upsert_battle_status_message(channel)


@battle_expiry_loop.before_loop
async def before_battle_expiry_loop() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    runtime_config.load()
    apply_runtime_config()
    battle_manager.load_state()
    points_manager.load_state()

    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    logger.info("Watching battle channel: %s", settings.battle_channel_id)
    logger.info("Battle timeout: %s seconds", current_timeout_seconds())
    logger.info("Battle state file: %s", settings.state_file_path)
    logger.info("User stats file: %s", settings.user_stats_file_path)
    logger.info("Champ role name: %s", current_champ_role_name())
    logger.info("Chaos role name: %s", current_chaos_role_name())

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
    if ctx.command.name in {"endbattle", "ping"}:
        return True
    allowed = await ensure_chaos_access_for_context(ctx)
    if not allowed:
        await send_chaos_role_required_response(ctx)
    return allowed


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.CheckFailure):
        if interaction.command and interaction.command.qualified_name.startswith("admin"):
            message = "You need Manage Server permission to use this admin command."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
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
        embed=build_battle_status_embed(
            guild=interaction.guild,
            active_round=active_round,
            timeout_seconds=current_timeout_seconds(),
        ),
        ephemeral=True,
    )


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="profile", description="Show Chaos Points, XP, level, and streak stats.")
@app_commands.describe(member="Optional member to inspect")
async def profile_slash(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    target = member or interaction.user
    assert isinstance(target, discord.Member)
    await interaction.response.send_message(embed=build_profile_embed(target), ephemeral=True)


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="leaderboard", description="Show the top Chaos leaderboard.")
async def leaderboard_slash(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_leaderboard_embed(interaction.guild), ephemeral=True)


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="champ", description="Show the current GIF Battle Champ.")
async def champ_slash(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return
    await interaction.response.send_message(embed=build_champ_embed(guild), ephemeral=True)


@app_commands.default_permissions(manage_guild=True)
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

    summary_embed = await finalize_battle_round(finished_round=finished_round, guild=interaction.guild, manual_end=True)
    await interaction.response.send_message(embed=summary_embed)


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

    await ctx.send(embed=build_battle_status_embed(guild=ctx.guild, active_round=active_round, timeout_seconds=current_timeout_seconds()))


@bot.command(name="points", aliases=["profile"])
async def points_prefix(ctx: commands.Context, member: discord.Member | None = None) -> None:
    target = member or ctx.author
    assert isinstance(target, discord.Member)
    await ctx.send(embed=build_profile_embed(target))


@bot.command(name="leaderboard")
async def leaderboard_prefix(ctx: commands.Context) -> None:
    await ctx.send(embed=build_leaderboard_embed(ctx.guild))


@bot.command(name="champ")
async def champ_prefix(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("This command only works in a server.")
        return
    await ctx.send(embed=build_champ_embed(ctx.guild))


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

    summary_embed = await finalize_battle_round(finished_round=finished_round, guild=ctx.guild, manual_end=True)
    await ctx.send(embed=summary_embed)


@endbattle_prefix.error
async def endbattle_prefix_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need Manage Server permission to use !endbattle.")
        return
    raise error


@app_commands.check(ensure_chaos_access_for_interaction)
@bot.tree.command(name="pingbattle", description="Check whether the bot is alive.")
async def ping_slash(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("🏓 GIF Battle bot is awake.", ephemeral=True)


admin_group = app_commands.Group(name="admin", description="Admin commands for the GIF Battle bot.")
config_group = app_commands.Group(name="config", description="View or update live bot config.", parent=admin_group)


@config_group.command(name="show", description="Show the current runtime config.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def admin_config_show(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_admin_config_embed(), ephemeral=True)


@config_group.command(name="set", description="Update a runtime config value.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(setting="Which runtime setting to update", value="New value")
@app_commands.choices(
    setting=[
        app_commands.Choice(name="battle_timeout_seconds", value="battle_timeout_seconds"),
        app_commands.Choice(name="chaos_role_name", value="chaos_role_name"),
        app_commands.Choice(name="champ_role_name", value="champ_role_name"),
        app_commands.Choice(name="participation_xp", value="participation_xp"),
        app_commands.Choice(name="win_xp", value="win_xp"),
        app_commands.Choice(name="streak_bonus_xp", value="streak_bonus_xp"),
        app_commands.Choice(name="reaction_xp_per_bonus_point", value="reaction_xp_per_bonus_point"),
        app_commands.Choice(name="level_base_xp", value="level_base_xp"),
        app_commands.Choice(name="level_step_xp", value="level_step_xp"),
    ]
)
async def admin_config_set(interaction: discord.Interaction, setting: app_commands.Choice[str], value: str) -> None:
    key = setting.value
    int_settings = {
        "battle_timeout_seconds",
        "participation_xp",
        "win_xp",
        "streak_bonus_xp",
        "reaction_xp_per_bonus_point",
        "level_base_xp",
        "level_step_xp",
    }

    try:
        parsed_value: int | str = int(value) if key in int_settings else value.strip()
    except ValueError:
        await interaction.response.send_message(f"`{value}` is not a valid integer for `{key}`.", ephemeral=True)
        return

    if isinstance(parsed_value, int) and parsed_value <= 0:
        await interaction.response.send_message("Numeric config values must be greater than 0.", ephemeral=True)
        return
    if isinstance(parsed_value, str) and not parsed_value:
        await interaction.response.send_message("Text config values cannot be empty.", ephemeral=True)
        return

    runtime_config.update(key, parsed_value)
    apply_runtime_config()

    await interaction.response.send_message(
        f"Updated **{key}** to `{parsed_value}`.",
        embed=build_admin_config_embed(),
        ephemeral=True,
    )


bot.tree.add_command(admin_group, guild=discord.Object(id=settings.guild_id) if settings.guild_id else None)


def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
