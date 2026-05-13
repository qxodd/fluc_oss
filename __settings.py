import discord
from discord import ui
from typing import Optional
from user import User


class ChannelSettings(ui.Modal):
    def __init__(self) -> None:
        super().__init__(title='Channel Settings', timeout=None)


class BetaSettings(ui.View):
    def __init__(self, user: Optional[User]):
        self.user = user

    async def disable(self, interaction: discord.Interaction):
        self.button_channel_settings.disabled = True
        self.button_guild_settings.disabled = True
        self.button_role_settings.disabled = True
        self.button_emoji_settings.disabled = True
        self.button_sticker_settings.disabled = True
        self.button_soundboard_settings.disabled = True
        self.button_invite_settings.disabled = True
        self.button_automod_settings.disabled = True
        self.button_template_settings.disabled = True
        self.button_webhook_settings.disabled = True
        self.button_message_settings.disabled = True
        self.button_no_admin_settings.disabled = True
        await interaction.response.edit_message(view=self)
            
    @ui.button(label='Channel Settings', custom_id='button_channel_settings')
    async def button_channel_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Server Settings', custom_id='button_guild_settings')
    async def button_guild_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Role Settings', custom_id='button_role_settings')
    async def button_role_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Emoij Settings', custom_id='button_emoji_settings')
    async def button_emoji_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Sticker Settings', custom_id='button_sticker_settings')
    async def button_sticker_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Soundboard Settings', custom_id='button_soundboard_settings')
    async def button_soundboard_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Invite Settings', custom_id='button_invite_settings')
    async def button_invite_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Automod Settings', custom_id='button_automod_settings')
    async def button_automod_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Template Settings', custom_id='button_template_settings')
    async def button_template_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Webhook Settings', custom_id='button_webhook_settings')
    async def button_webhook_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='Message Settings', custom_id='button_message_settings')
    async def button_message_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())
            
    @ui.button(label='No-admin Settings', custom_id='button_no_admin_settings')
    async def button_no_admin_settings(self, interaction: discord.Interaction, _):
        if not self.user:
            return await self.disable(interaction)
        await interaction.response.send_modal(ChannelSettings())