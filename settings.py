import discord
import shared
from user import User, Settings
from shared import get_embed
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal

db = shared.db

class Set(commands.GroupCog):
    async def set_settings(self, interaction: discord.Interaction, name: str, data: dict) -> bool:
        user = await db.get_user(interaction.user.id)
        if not user:
            user = User.new(interaction.user.id)
            await db.add_user(user)
        settings = user._settings
        if settings is None:
            settings = {}
        master = settings.setdefault(name, {})
        for key, value in data.items():
            if value:
                master[key] = [value]
            elif str(value).lower() in ('-1', 'None'):
                master.pop(key, None)
        new_settings = Settings(settings)
        if await db.update_settings(user.id, new_settings):
            embed = get_embed(f'Settings updated.')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return True
        embed = get_embed('Settings not updated')
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    
    async def cog_check(self, ctx: commands.Context) -> bool:
        user = await db.get_user(ctx.author.id)
        if not user:
            await ctx.reply('You must log in with Discord on [fluc.lol](https://fluc.lol/account/login) to use this command.')
            return False
        if user.is_blacklisted:
            return False
        # if not user.is_premium and not user.is_elevated:
        #     await ctx.reply('Only premium users can manage settings.')
        #     return False
        return True

    @app_commands.command(name='autonuke')
    @app_commands.describe(
        delay='Delay in seconds for auto nake. Set to -1 to disable auto nake.'
    )
    async def autonuke(
        self,
        interaction: discord.Interaction,
        delay: Optional[app_commands.Range[int, -1, 60 * 60]] = 0
    ):
        if not delay:
            delay = 0
        user = await db.get_user(interaction.user.id)
        if not user:
            user = User.new(interaction.user.id)
            await db.add_user(user)
        settings = user._settings
        if settings is None:
            settings = user._settings = {}
        master = settings.setdefault('master', {})
        if delay == -1:
            master.pop('auto_nuke', None)
        else:
            master['auto_nuke'] = [max(-1, delay if delay is not None else -1)]
        new_settings = Settings(settings)
        if await db.update_settings(user.id, new_settings):
            embed = get_embed('Settings updated')
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        embed = get_embed('Settings not updated')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='prefix')
    @app_commands.describe(
        prefix='Prefix for bot commands.'
    )
    async def prefix(
        self,
        interaction: discord.Interaction,
        prefix: Optional[app_commands.Range[str, 0, 5]] = None
    ):
        await self.set_settings(
            interaction,
            'master',
            {
                'command_prefix': prefix
            }
        )

    @app_commands.command(name='message')
    @app_commands.describe(
        content='The message bot should send.',
        tts='Whether the messages should be sent as tts.',
        amount='Amount of messages to send.'
    )
    async def message(
        self,
        interaction: discord.Interaction,
        content: Optional[app_commands.Range[str, 0, 2000]] = None,
        tts: Optional[bool] = None,
        amount: Optional[app_commands.Range[int, -1, 42]] = None
    ):
        if amount == 0:
            amount = -1
        await self.set_settings(
            interaction,
            'message',
            {
                'content': content,
                'tts': tts,
                'amount': amount
            }
        )

    @app_commands.command(name='webhook')
    @app_commands.describe(
        username='The username of webhook.',
        avatar_url='Avatar URL of webhook.'
    )
    async def webhook(
        self,
        interaction: discord.Interaction,
        username: Optional[app_commands.Range[str, 0, 32]] = None,
        avatar_url: Optional[app_commands.Range[str, 1, 200]] = None
    ):
        await self.set_settings(
            interaction,
            'webhook',
            {
                'username': username,
                'avatar_url': avatar_url
            }
        )

    @app_commands.command(name='server')
    @app_commands.describe(
        name='Name of server.',
        icon='Icon of server',
        banner='Banner of server.',
        # community='Whether community modes should be enabled for server (slow).'
    )
    async def server(
        self,
        interaction: discord.Interaction,
        name: Optional[app_commands.Range[str, 0, 100]] = None,
        icon: Optional[app_commands.Range[str, 0, 200]] = None,
        banner: Optional[app_commands.Range[str, 0, 200]] = None,
        # community: Optional[bool] = None,
    ):
        await self.set_settings(
            interaction,
            'guild',
            {
                'name': name,
                'icon': icon,
                'banner': banner,
                # 'community': community
            }
        )

    @app_commands.command(name='channel')
    @app_commands.describe(
        name='Name of channel.',
        topic='Topic of channel',
        nsfw='Whether channel should be marked as NSFW.',
        slowmode_delay='Slowmode delay in seconds.'
    )
    async def channel(
        self,
        interaction: discord.Interaction,
        name: Optional[app_commands.Range[str, 0, 20]] = None,
        topic: Optional[app_commands.Range[str, 0, 100]] = None,
        nsfw: Optional[bool] = None,
        slowmode_delay: Optional[app_commands.Range[str, 0, 6000]] = None
    ):
        await self.set_settings(
            interaction,
            'channel',
            {
                'name': name,
                'topic': topic,
                'nsfw': nsfw,
                'slowmode_delay': slowmode_delay
            }
        )

    @app_commands.command(name='reset', description='Resets settings')
    async def reset(self,
        interaction: discord.Interaction,
        category: Optional[Literal[
            'autonake',
            'command_prefix',
            'message',
            'webhook',
            'server',
            'channel'
        ]] = None
    ):
        user = await db.get_user(interaction.user.id)
        result = False
        settings = None
        if user:
            settings = user._settings
            if category and settings:
                if category in ('autonake', 'command_prefix'):
                    if category in settings['master']:
                        del settings['master'][category]
                else:
                    if category in settings:
                        del settings[category]

        if user:
            if category and settings:
                result = await db.update_settings(user.id, Settings(settings))
            else:
                result = await db.delete_settings(user.id)
        
        if user and result:
            embed = get_embed('Settings updated')
        else:
            embed = get_embed('Settings not updated')
        await interaction.response.send_message(embed=embed, ephemeral=True)