from __future__ import annotations

import discord
import requests
import asyncio
import queue
import utils
from logging import getLogger
from requests.adapters import HTTPAdapter
from time import sleep
from urllib.parse import urlencode
from discord import ui
from about import __version__
from user import Settings
from default import server_icon, cross, check, p_name
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Awaitable, Optional, List, TypedDict, Generator, Dict, Tuple

log = getLogger(__name__)
state = {}


class TButton(TypedDict):
    label: str
    style: discord.ButtonStyle
    callback: Callable[[Buttons, discord.Interaction, ui.Button], Awaitable]
    custom_id: Optional[str]


class DmButton(ui.View):
    def __init__(self, bot_id: int, *, user_intall: bool = False):
        super().__init__(timeout=None)
        if user_intall:
            params = {
                'client_id': bot_id,
                'integration_type': 1,
                'scope': 'applications.commands'
            }
        else:
            params = {
                'client_id': bot_id,
                'permissions': 1099511627775,
                'scope': 'bot'
            }
        
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.link,
            url=f'https://discord.com/oauth2/authorize?' + urlencode(params)  
        )
        if not bot_id:
            button.disabled = True
        self.add_item(button)


class InviteButton(ui.View):
    def __init__(self, bot_id: int):
        super().__init__(timeout=None)
        self.bot_id = bot_id
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.primary,
            custom_id=f'button_nuke'
        )
        button.callback = self.callback
        self.add_item(button)

    async def callback(self, interaction: discord.Interaction, *, retry: int = 0):
        if not retry:
            await interaction.response.defer(ephemeral=True, thinking=True)
        last_invite: Optional[float] = state.get(interaction.user.id)
        if last_invite:
            delay = utils.now().timestamp() - last_invite
            if delay < 10:
                embed = discord.Embed(
                    title='Warning',
                    description=f'You are on cooldown. Please retry in {int(delay)} seconds.',
                    color=discord.Color.yellow()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        try:
            message = await interaction.user.send(
                embed=self.embed(),
                view=DmButton(self.bot_id),
                delete_after=60
            )
            state[interaction.user.id] = utils.now().timestamp()
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Success!',
                    description=f'{check} The bot invite has been sent to your DMs {message.jump_url}!',
                    color=discord.Color.blue()
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Error',
                    description=f'{cross} Please enable your DMs in order to get the invite.'
                ),
                ephemeral=True
            )
        except discord.HTTPException:
            # Could be rate limit due to opening DMs too fast
            # Discord returns 400 instead of 429 in such case
            if not retry:
                await interaction.followup.send('Bot invite will be sent to your DMs in a few moments..', ephemeral=True)
                log.warning(f'Rate limited while attempting to open DM for: {interaction.user.id}.')
            else:
                log.warning(f'Rate limited while attempting to open DM for: {interaction.user.id} after {retry * 5}s cooldown.')
            await asyncio.sleep(5)
            return await self.callback(interaction, retry=retry + 1)

    @staticmethod
    def embed():
        return discord.Embed(
            title='Bot Invite',
            description='Click on the button below to add the bot to your server.\n-# Note: administrator permissions are required in order to add the bot.',
            color=discord.Color.green()
        )


class InviteNoadminButton(ui.View):
    def __init__(self, bot_id: int):
        super().__init__(timeout=None)
        self.bot_id = bot_id
        button = ui.Button(
            label='🤖 Add Bot',
            style=discord.ButtonStyle.primary,
            custom_id=f'button_noadmin'
        )
        button.callback = self.callback
        self.add_item(button)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            message = await interaction.user.send(
                embed=self.embed(),
                view=DmButton(self.bot_id, user_intall=True),
                delete_after=60
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Success!',
                    description=f'{check} The bot invite has been sent to your DMs {message.jump_url}!',
                    color=discord.Color.blue()
                ),
                ephemeral=True
            )
        
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(
                    title='Error',
                    description=f'{cross} Please enable your DMs in order to get the invite.'
                ),
                ephemeral=True
            )

    @staticmethod
    def embed():
        return discord.Embed(
            title='No-admin Bot Invite',
            description='Click on the button below to add the bot to your account.',
            color=discord.Color.green()
        )


class Paginated(ui.View):
    def __init__(self, embed: discord.Embed, fields: list[dict]):
        super().__init__(timeout=None)
        self.embed = embed
        self.batches: list[list[dict]] = []
        self.page = 1
        self.per_page = 10
        for i in range(0, len(fields), self.per_page):
            self.batches.append(fields[i:i+self.per_page])
        self._update()

    @ui.button(label='⏮️ Previous Page', custom_id='button_previous')
    async def button_previous(self, interaction: discord.Interaction, _):
        self.page -= 1
        await self.update(interaction)

    @ui.button(label='Next Page ⏭️', custom_id=f'button_next')
    async def button_next(self, interaction: discord.Interaction, _):
        self.page += 1
        await self.update(interaction)

    def _update(self):
        if self.page == len(self.batches):
            self.button_next.disabled = True
            self.button_previous.disabled = False
        elif self.page == 1:
            self.button_next.disabled = False
            self.button_previous.disabled = True
        else:
            self.button_previous.disabled = False
            self.button_next.disabled = False
        
        self.embed.clear_fields()
        for field in self.batches[self.page - 1]:
            self.embed.add_field(name=field['name'], value=field['value'], inline=field['inline'])
        self.embed.set_footer(icon_url=server_icon,text=f'Page {self.page}/{len(self.batches)} | Powered by {p_name} v{__version__}')

    async def update(self, interaction: discord.Interaction) -> None:
        self._update()
        await interaction.response.edit_message(embed=self.embed, view=self)


class HelpMenu(Paginated):
    ...


class ServerMenu(Paginated):
    ...


class Buttons(ui.View):
    def __init__(self, *buttons: TButton):
        super().__init__(timeout=None)
        for _button in buttons:
            button = ui.Button(
                label=_button['label'],
                style=_button['style'],
                custom_id=_button['custom_id']
            )
            async def callback(interaction: discord.Interaction, button=button, data=_button):
                await _button['callback'](self, interaction, button)
            button.callback = callback
            self.add_item(button)


class ChannelSpam:
    def __init__(self):
        self.queue = queue.Queue()
        self.interactions: List[discord.Interaction] = []
        self.workers = 20
        self.stopped = False
        self.sending = False
        self.executor = None

    def submit(self, view: SpamView):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=self.workers)
        interactions = self.interactions.copy()
        self.interactions.clear()
        gen = view.get_followup(interactions)
        for _ in range(30):
            try:
                followup = next(gen)
            except StopIteration:
                return
            self.executor.submit(view.send_message, followup, self)
        for followup in gen:
            self.queue.put((followup, 1.5))

    def consume(self, view: SpamView):
        while True:
            try:
                followup, retry_after = self.queue.get(timeout=5)
            except queue.Empty:
                break
            if self.stopped:
                break
            sleep(retry_after)
            view.send_message(followup, self)
            self.queue.task_done()

        self.sending = False
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None

    def stop(self):
        self.interactions.clear()
        self.stopped = True
        with self.queue.mutex:
            self.queue.queue.clear()
        self.sending = False
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None


class SpamView(ui.View):
    interactions: List[discord.Interaction]
    views: Dict[Tuple[int, int], ChannelSpam] = {}

    def __init__(self, settings: Optional[Settings], interaction: Optional[discord.Interaction] = None):
        super().__init__(timeout=None)
        self.settings = settings and settings.no_admin or None
        # Constant 500
        self.limit = 500
        self.embed = discord.Embed(
            title='Panel',
            description='Click "+5 messages" if you want to make the bot send more messages.\nClick "Fire" to start spamming.'
        )
        self.embed.set_footer(text=f'Powered by {p_name} v{__version__}', icon_url=server_icon)
        state = type(self).get_state(interaction)
        if interaction:
            state.interactions.append(interaction)
        self.update_queue(base=interaction and 10 or 5)

    @classmethod
    def get_state(cls, interaction: Optional[discord.Interaction] = None) -> ChannelSpam:
        if interaction is None:
            return ChannelSpam()
        channel_id = interaction.channel_id
        if channel_id is None:
            channel_id = getattr(interaction.channel, 'id', None)
        if channel_id is None:
            return ChannelSpam()
        user_id = interaction.user.id
        key = (channel_id, user_id)
        state = cls.views.get(key)
        if state is None:
            state = ChannelSpam()
            cls.views[key] = state
        return state

    def update_queue(self, interaction: Optional[discord.Interaction] = None, base: int = 5, ignore_queue: bool = False):
        state = self.get_state(interaction)
        self.embed.clear_fields()
        self.embed.add_field(name='Queue', value=f'{ignore_queue and base or len(state.interactions) * 5 + base} messages will be sent.')

    def get_followup(self, interactions: List[discord.Interaction]) -> Generator[discord.Webhook, None, None]:
        for interaction in interactions[:]:
            for _ in range(5):
                yield interaction.followup
            interactions.remove(interaction)

    def submit(self, state: ChannelSpam):
        state.submit(self)

    def send_message(self, followup: discord.Webhook, state: ChannelSpam):
        if not self.settings:
            return
        session = requests.Session()
        # Make session be able to handle state.workers concurrent requests
        adapter = HTTPAdapter(pool_connections=state.workers, pool_maxsize=state.workers)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        data = {
            'content': self.settings.content,
            'tts': self.settings.tts,
            'embeds': [self.settings.embed.to_dict()] if self.settings.embed else [],
            'allowed_mentions': {
                'parse': [
                    'everyone',
                    'users',
                    'roles'
                ]
            }
        }
        if state.stopped:
            return
        response = session.post(f'https://discord.com/api/v10/webhooks/{followup.id}/{followup.token}', json=data)
        if response.status_code == 429:
            json_data = response.json()
            retry_after = json_data.get('retry_after')
            state.queue.put((followup, float(retry_after)))
            return
        if 200 <= response.status_code < 300:
            try:
                json_data = response.json()
            except ValueError:
                return
            flags = json_data.get('flags')
            if isinstance(flags, int) and flags & 0x40:
                # Message was sent as ephemeral - external app perms disabled
                state.stop()
                return
        if response.status_code == 403:
            try:
                json_data = response.json()
                error_message = json_data.get('message', '')
            except ValueError:
                error_message = response.text
            if 'external app' in error_message.lower() or 'disallowed' in error_message.lower() or 'cannot send messages' in error_message.lower():
                state.stop()
                return

    async def update(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.embed, view=self)

    async def disable(self, interaction: discord.Interaction):
        self.button_add.disabled = True
        self.button_fire.disabled = True
        self.button_stop.disabled = True
        await self.update(interaction)

    @ui.button(label='+5 messages', custom_id='plus_5_messages')
    async def button_add(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        state = type(self).get_state(interaction)
        state.interactions.append(interaction)
        self.update_queue(interaction)
        if len(state.interactions) >= self.limit // 5 - 1:
            self.button_add.disabled = True
        await self.update(interaction)

    @ui.button(label='🔥FIRE', custom_id='fire')
    async def button_fire(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        self.button_add.disabled = False
        state = type(self).get_state(interaction)
        state.stopped = False
        state.interactions.append(interaction)
        self.update_queue(ignore_queue=True)
        asyncio.create_task(self.update(interaction))

        if state.sending and state.executor:
            self.submit(state)
            return

        state.sending = True
        self.submit(state)
        assert state.executor is not None
        state.executor.submit(state.consume, self)

    @ui.button(label='🛑Stop', custom_id='button_stop')
    async def button_stop(self, interaction: discord.Interaction, _):
        if not self.settings:
            return await self.disable(interaction)
        state = type(self).get_state(interaction)
        await interaction.response.defer(ephemeral=True)
        state.stop()


# class TokenSpamView(ui.View):
#     def __init__(self, interaction: discord.Interaction, settings: Settings, tokens: List[str]):
#         super().__init__(timeout=None)
#         self.interaction = interaction
#         self.settings = settings
#         self.tokens = tokens
#         self.embed = discord.Embed()