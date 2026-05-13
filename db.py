import discord
import shared
from shared import get_embed
from user import User
from discord import app_commands
from discord.ext import commands
from typing import Optional

db = shared.db

class Db(commands.GroupCog, name='database'):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.main_server = shared.main_server
        super().__init__()

    async def cog_check(self, ctx: commands.Context) -> bool:
        user = await db.get_user(ctx.author.id)
        if not user:
            await ctx.defer(ephemeral=True)
            return False
        
        if not user.is_elevated:
            await ctx.defer(ephemeral=True)
            return False
        return True
        
    @app_commands.command(description='Wipes database.')
    async def wipe(self, interaction: discord.Interaction):
        user = await db.get_user(interaction.user.id)
        assert user
        if not user.is_owner:
            embed = get_embed('You cannot run this command at this time', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        await interaction.response.defer(ephemeral=True)

    @app_commands.command(description='Adds a Fluc user.')
    async def add_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        is_super: Optional[bool] = False
    ):
        kwargs = {}
        if is_super:
            mod = await db.get_user(interaction.user.id)
            assert mod
            if mod.is_owner:
                kwargs.update({'is_super': True})
        user_ = User.new(user.id, **kwargs)
        if await db.add_user(user_):
            embed = get_embed('Added user to database.')
        else:
            embed = get_embed('Could not add user to database.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Deletes a Fluc user.')
    async def delete_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        blacklist: Optional[bool] = False
    ):
        user_ = await db.get_user(user.id)
        if not user_:
            embed = get_embed('User not found', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if blacklist:
            await db.add_user_blacklist(user_.id)
        if user_.is_elevated:
            if user_.is_owner:
                embed = get_embed('I cannot delete this user.', 'warning')
                await interaction.response.send_message(embed=embed)
                return
            elif user_.is_super:
                author = await db.get_user(interaction.user.id)
                assert author
                if not author.is_owner:
                    embed = get_embed('You cannot delete this user.', 'warning')
                    await interaction.response.send_message(embed=embed)
                    return
        if await db.delete_user(user_.id):
            embed = get_embed('This user has been deleted.')
        else:
            embed = get_embed('Could not delete this user.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Adds a super user.')
    async def add_super(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        author = await db.get_user(interaction.user.id)
        assert author
        if not author.is_owner:
            embed = get_embed('You cannot perform this action.')
            await interaction.response.send_message(embed=embed)
            return
        user_ = await db.get_user(user.id)
        if not user_:
            embed = get_embed('User not found', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        member = self.main_server.get_member(user.id)
        if await db.add_super(user_.id):
            if member:
                role = discord.Object(shared.roles['moderator'])
                await member.add_roles(role)
            embed = get_embed('Super user added.')
        else:
            embed = get_embed('Could not add this super user.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Removes a super user.')
    async def remove_super(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        author = await db.get_user(interaction.user.id)
        assert author
        if not author.is_owner:
            embed = get_embed('You cannot perform this action.')
            await interaction.response.send_message(embed=embed)
            return
        user_ = await db.get_user(user.id)
        if not user_:
            embed = get_embed('User not found', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if await db.delete_super(user_.id):
            member = self.main_server.get_member(user.id)
            if member:
                role = discord.Object(shared.roles['moderator'])
                await member.remove_roles(role)
            embed = get_embed('Super user deleted.')
        else:
            embed = get_embed('Could not delete this super user.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Blacklists a user.')
    async def blacklist_user(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        user_ = await db.get_user(user.id)
        if user_:
            if user_.is_elevated:
                embed = get_embed('Could not blacklist this user.', 'warning')
                await interaction.response.send_message(embed=embed)
                return
        if await db.add_user_blacklist(user.id):
            member = self.main_server.get_member(user.id)
            if member:
                role = discord.Object(shared.roles['blacklist'])
                await member.edit(roles=[role])
            embed = get_embed('User blacklisted.')
        else:
            embed = get_embed('Could not blacklist this user.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Removes a user from blacklist.')
    async def remove_blacklist_user(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        if await db.delete_user_blacklist(user.id):
            member = self.main_server.get_member(user.id)
            if member:
                role = discord.Object(shared.roles['blacklist'])
                await member.remove_roles(role)
            embed = get_embed('Removed user from blacklist.')
        else:
            embed = get_embed('Could not remove this user from blacklist.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Blacklists a server.')
    async def blacklist_server(
        self,
        interaction: discord.Interaction,
        server_id: str
    ):
        try:
            server_id_ = int(server_id)
        except Exception:
            embed = get_embed('Invalid server ID.', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if await db.add_server_blacklist(server_id_):
            embed = get_embed('Server blacklisted.')
        else:
            embed = get_embed('Could not blacklist this server.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Removes a server from blacklist.')
    async def remove_blacklist_server(
        self,
        interaction: discord.Interaction,
        server_id: str
    ):
        try:
            server_id_ = int(server_id)
        except Exception:
            embed = get_embed('Invalid server ID.', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if await db.delete_server_blacklist(server_id_):
            embed = get_embed('Removed server from blacklist.')
        else:
            embed = get_embed('Could not remove this server from blacklist.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Add premium to a user.')
    async def add_premium(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        user_ = await db.get_user(user.id)
        if not user_:
            embed = get_embed('User not found.', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if await db.add_premium(user_.id):
            member = self.main_server.get_member(user.id)
            if member:
                role = discord.Object(shared.roles['premium'])
                await member.add_roles(role)
            embed = get_embed('Added premium to this user.')
        else:
            embed = get_embed('Could not add premium to this user.', 'warning')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description='Removes premium from a user.')
    async def remove_premium(
        self,
        interaction: discord.Interaction,
        user: discord.User
    ):
        user_ = await db.get_user(user.id)
        if not user_:
            embed = get_embed('User not found.', 'warning')
            await interaction.response.send_message(embed=embed)
            return
        if await db.delete_premium(user_.id):
            member = self.main_server.get_member(user.id)
            if member:
                role = discord.Object(shared.roles['premium'])
                await member.remove_roles(role)
            embed = get_embed('Removed premium from this user.')
        else:
            embed = get_embed('Could not remove this user from premium.', 'warning')
        await interaction.response.send_message(embed=embed)