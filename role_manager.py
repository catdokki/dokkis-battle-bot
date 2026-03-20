from __future__ import annotations

import logging

import discord


logger = logging.getLogger("gif_battle_bot.role_manager")


class RoleManager:
    def __init__(self, champ_role_name: str) -> None:
        self.champ_role_name = champ_role_name

    async def get_or_create_champ_role(self, guild: discord.Guild) -> discord.Role | None:
        role = discord.utils.get(guild.roles, name=self.champ_role_name)
        if role is not None:
            return role

        try:
            role = await guild.create_role(
                name=self.champ_role_name,
                reason="GIF Battle Champ role auto-created by bot.",
                mentionable=True,
            )
            logger.info("Created champ role '%s' in guild %s", self.champ_role_name, guild.id)
            return role
        except discord.Forbidden:
            logger.warning(
                "Missing permission to create role '%s' in guild %s",
                self.champ_role_name,
                guild.id,
            )
            return None
        except discord.HTTPException as exc:
            logger.warning(
                "Failed to create role '%s' in guild %s: %s",
                self.champ_role_name,
                guild.id,
                exc,
            )
            return None

    async def assign_champ_role(
        self,
        guild: discord.Guild,
        winner_user_id: int,
    ) -> tuple[discord.Role | None, discord.Member | None]:
        role = await self.get_or_create_champ_role(guild)
        if role is None:
            return None, None

        winner = guild.get_member(winner_user_id)
        if winner is None:
            try:
                winner = await guild.fetch_member(winner_user_id)
            except discord.NotFound:
                logger.warning("Winner %s not found in guild %s", winner_user_id, guild.id)
                return role, None
            except discord.Forbidden:
                logger.warning("Missing permission to fetch members in guild %s", guild.id)
                return role, None
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to fetch winner %s in guild %s: %s",
                    winner_user_id,
                    guild.id,
                    exc,
                )
                return role, None

        members_to_remove = [member for member in role.members if member.id != winner_user_id]

        for member in members_to_remove:
            try:
                await member.remove_roles(role, reason="New GIF Battle Champ crowned.")
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to remove role '%s' from user %s",
                    role.name,
                    member.id,
                )
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to remove role '%s' from user %s: %s",
                    role.name,
                    member.id,
                    exc,
                )

        if role not in winner.roles:
            try:
                await winner.add_roles(role, reason="Won GIF Battle round.")
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to add role '%s' to winner %s",
                    role.name,
                    winner.id,
                )
                return role, winner
            except discord.HTTPException as exc:
                logger.warning(
                    "Failed to add role '%s' to winner %s: %s",
                    role.name,
                    winner.id,
                    exc,
                )
                return role, winner

        return role, winner