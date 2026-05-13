import discord
import database
import asyncio
import logging
import utils
import aiohttp
from traceback import TracebackException
from orjson import loads
from uuid import uuid4
from collections import defaultdict
from user import Settings, Permissions, User
from datetime import datetime, UTC
from components import HelpMenu
from discord.ext import commands
from default import cross, check, p_name, website
from about import __version__
from host import Datalix, Service
import pydactyl
from typing import (
    List, Optional, Literal, Callable, Awaitable,
    Any, Dict, Union, Tuple
)

class EmptyAsyncClient:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc, tb):
        pass

with open('config/config.json') as file:
    config = loads(file.read())

with open('config/roles.json') as file:
    roles = loads(file.read())

log = logging.getLogger()
running = defaultdict(set)
locks = defaultdict(asyncio.Semaphore)
datalix: Union[Datalix, EmptyAsyncClient] = EmptyAsyncClient()
datalix_service: Optional[Service] = None
dactyl: Union[pydactyl.async_api_client.AsyncClientAPI, EmptyAsyncClient] = EmptyAsyncClient()
server: Optional[str]
has_host: bool
main_server: discord.Guild
rate_limit: bool = False
# Amount of commands allowed to be executed at once per user
user_command_semaphore = defaultdict(lambda: asyncio.Semaphore(config['user_command_concurrency']))
# Amount of commands allowed to be executed at once globally
global_command_semaphore = asyncio.Semaphore(config['global_command_concurrency'])


class Cooldowns:
    rate_limits: Dict[str, Dict[int, float]]
    'Dict[command_name: Dict[user_id/server_id, timestamp_expires, min_members]]'
    cooldowns: Dict[str, Tuple[int, int, bool, bool, Optional[int]]]
    'Dict[command_name: (server_cooldown, user_cooldown, server_cooldown_enabled, user_cooldown_enabled)]'
    permissions: Dict[str, Optional[discord.Permissions]]
    'Dict[command_name: discord.Permissions]'
    # Basically ellipsis (the one we're supposed to use in 3.14) is not a thing in previous versions, that's why we use Ellipsis
    callbacks: Dict[str, Tuple[Callable[..., Awaitable[Any]], Union[Permissions, Ellipsis], Union[Callable[..., Awaitable[Any]], Ellipsis], Optional[Union[str, Ellipsis]]]] # pyright: ignore[reportInvalidTypeForm]
    'Dict[command_name: (coro, .../Permissions, .../wrapper, .../doc)]'
    aliases: Dict[str, List[str]]
    'Dict[command_name: alias_name]'
    warned_users: Dict[Tuple[str, int, int], float] = {}
    'Dict[(command_name, author_id, channel_id): timestamp_expires]'
    to_check: Dict[str, List[str]]
    'Dict[command_name: [command_name/alias_name]]'
    
    def __init__(self) -> None:
        self.rate_limits = defaultdict(dict)
        self.cooldowns = {}
        self.warned_users = {}
        self.permissions = {}
        self.callbacks = {}
        self.aliases = {}
        self.to_check = {}

    def check(
        self,
        cooldown: int,
        *,
        user_cooldown: bool = True,
        server_cooldown: bool = False,
        aliases: Optional[List[str]] = None,
        min_members: Optional[int] = None
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        '''
        Decorator that registers a command so it can be used for cooldowns

        Parameters
        ----------
        cooldown : :class:`int`
            Cooldown in seconds
        user_cooldown : Optional[bool]
            Whether to apply cooldown for user, by default True
        server_cooldown : Optional[bool]
            Whether to apply cooldown for server, by default False
        aliases : Optional[Liststr]]
            Command aliases, by default None
        min_members : Optional[:class:`int`]
            Required member amount in server to run this command, by default None

        Returns
        -------
        Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]
            Decorator that registers command
        '''
        def decorator(coro: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            command = coro.__name__
            command = command.removeprefix('cmd_')
            self.callbacks[command] = (coro, ..., ..., coro.__doc__)
            self.cooldowns[command] = (int(cooldown), int(min(60, cooldown)), bool(user_cooldown), bool(server_cooldown), min_members)

            if aliases:        
                self.aliases[command] = aliases
            return coro
        return decorator

    def add_command(
        self,
        command: str,
        permissions: Permissions,
        discord_permissions: Optional[discord.Permissions],
        wrapper: Callable[..., Awaitable[Any]],
        doc: Optional[str]
    ) -> None:
        '''
        Adds command to :attr:`~shared.Cooldowns.callbacks`

        Parameters
        ----------
        command : str
            Name of command
        permissions : :class:`~user.Permissions`
            Required Fluc permissions to run command
        discord_permissions : Optional[:class:`discord.Permissions`]
            Required Discord permissions to run command
        wrapper : Callable[..., Awaitable[Any]]
            Coroutine that runs command
        doc : Optionalstr]
            Doc for command
        '''
        callback = self.callbacks[command]
        func = callback[0]
        self.callbacks[command] = (func, permissions, wrapper, doc)
        self.permissions[command] = discord_permissions

    async def check_cooldown(
        self,
        command: str,
        guild_id: int,
        user_id: int,
        *,
        user_cooldown: bool = True,
        server_cooldown: bool = False,
        now: Optional[datetime] = None,
        apply_cd: bool = False,
        user: Optional[User] = None
    ) -> None:
        '''
        Checks if specified object is on cooldown

        If the object is not on cooldown, by default, a cooldown will be created

        Parameters
        ----------
        command : str
            The command to check
        guild_id : :class:`int`
            The ID of server to check
        user_id : :class:`int`
            The ID of user to check
        user_cooldown : Optional[bool]
            Whether to check user for cooldown, by default True
        server_cooldown : Optional[bool]
            Whether to check server for cooldown, by default False
        now : Optional[:class:`datetime.datetime`]
            Datetime when :arg:`command` was ran, by default None
        apply_cd : :class:bool
            Whether to apply/create cooldown, by default False
        user : Optional[:class:`~user.User`]
            User to check, by default None

        Raises
        ------
        :class:`discord.commands.CommandOnCooldown`
            Cooldown object
        '''
        if now is None:
            now = datetime.now(UTC)
        utcnow = int(now.timestamp())
        server_cd, user_cd = self.cooldowns[command][:2]
        rate_limits = {key: value for key, value in self.rate_limits[command].items() if value > utcnow}

        async def apply_cooldown(key: int, duration: float, bucket_type: commands.BucketType):
            if key not in rate_limits:
                cooldown = utcnow + duration + 3
                if user and user.is_premium:
                    # 25% less for premium users
                    cooldown = cooldown - (cooldown // 4)
                rate_limits[key] = cooldown

            else:
                remaining = rate_limits[key] - utcnow
                if remaining > 0:
                    raise commands.CommandOnCooldown(
                        commands.Cooldown(0, duration),
                        remaining,
                        bucket_type
                    )
                
        if server_cooldown:
            await apply_cooldown(guild_id, server_cd, commands.BucketType.guild)
                
        if user_cooldown:
            await apply_cooldown(user_id, user_cd, commands.BucketType.user)
                
        if apply_cd:
            self.rate_limits[command] = rate_limits

    def remove_cooldown(self, command: str, guild_id: int, user_id: int) -> bool:
        '''
        Removes a cooldown

        Parameters
        ----------
        command : str
            The command that is on cooldown
        guild_id : int
            Server ID of the server that's on cooldown 
        user_id : int
            User ID of the user that's on cooldown

        Returns
        -------
        bool
            Whether the cooldown was removed. If not, the cooldown was not found
        '''
        if command not in self.rate_limits:
            return False

        rate_limits = self.rate_limits[command]
        rate_limits.pop(guild_id, None)
        rate_limits.pop(user_id, None)

        if not rate_limits:
            del self.rate_limits[command]
            return True
        return False


db = database.Database()
cooldowns = Cooldowns()


async def get_prefix(bot: commands.Bot, message: discord.Message) -> List[str]:
    '''
    Returns command prefix for specific user

    Will return default or user specified prefix(es)

    Parameters
    ----------
    bot : :class:`discord.ext.commands.Bot`
        Bot that will execute the command
    message : :class:`discord.Message`
        The message that was sent

    Returns
    -------
    Liststr]
        List of prefixes
    '''
    user = await db.get_user(message.author.id)
    if not user:
        return Settings.default().command_prefix
    return user.settings.command_prefix

def get_embed(
    content: str,
    level: Optional[Literal['info', 'warning', 'error', '']] = 'info',
    header: Optional[str] = None,
    footer: Optional[str] = None,
    fields: Optional[List[Dict[str, str]]] = None
) -> discord.Embed:
    '''
    Helps easily construct a :class:`discord.Embed`

    Color map:
    - **info**: green
    - **warning**: yellow  
    - **error**: red

    Parameters
    ----------
    content : str
        Description of constructed :class:`discord.Embed`
    level : Optional[Literal['&#39;info&#39;, &#39;warning&#39;, &#39;error&#39;, &#39;&#39;]]
        Title of constructed :class:`discord.Embed` if ``header`` not specified, by default None
        Will also determine color for embed
    header : Optionalstr]
        Title of constructed :class:`discord.Embed`, by default ``level``
    footer : Optionalstr]
        Footer of constructed :class:`discord.Embed`, by default None
    fields : Optional[List[Dictstr, str]]]
        Fields of constructed :class:`discord.Embed`, by default None

    Returns
    -------
    :class:`discord.Embed`
        The constructed embed
    '''
    if not fields:
        fields = []

    if not level:
        level = ''

    level_map = {
        'info': [
            discord.Color.blue,
            check,
            'Success'
        ],
        'warning': [
            discord.Color.yellow,
            ':warning:',
            'Warning'
        ],
        'error': [
            discord.Color.red,
            cross,
            'Error'
        ],
        '': [
            discord.Color.green,
            '',
            ''
        ]
    }
    embed = discord.Embed(
        title=header or level_map[level][2],
        description=f'{level_map[level][1]} {content}',
        color=level_map[level][0]()
    )
    for field in fields:
        embed.add_field(inline=bool(field['inline']), name=field['name'], value=field['value'])
    if footer:
        embed.set_footer(text=footer)
    return embed

async def reply(
    message: discord.Message,
    content: str,
    level: Optional[Literal['info', 'warning', 'error', '']] = None,
    header: Optional[str] = None,
    footer: Optional[str] = None,
    fields: Optional[List[Dict[str, str]]] = None,
    **kwargs
) -> discord.Message:
    '''
    Constructs :class:`discord.Embed` and replies to ``message``

    Parameters
    ----------
    message : :class:`discord.Message`
        The message to reply to
    content : str
        Description of constructed :class:`discord.Embed`
    level : Optional[Literal['&#39;'info&#39;, &#39;warning&#39;, &#39;error&#39;, &#39;&#39;]]
        Title of constructed :class:`discord.Embed` if ``header`` not specified, by default None
    header : Optionalstr]
        Title of constructed :class:`discord.Embed`, by default ``level``
    footer : Optionalstr]
        Footer of constructed :class:`discord.Embed`, by default None
    fields : Optional[List[Dictstr, str]]]
        Fields of constructed :class:`discord.Embed`, by default None

    Returns
    -------
    :class:`discord.Message`
        Message that was sent
    '''
    embed = get_embed(content, level, header, footer, fields)
    message_sent = await message.reply(embed=embed, **kwargs)
    return message_sent

def command(permissions: Permissions = Permissions(), discord_permissions: discord.Permissions = discord.Permissions.none(), keep_message: bool = False):
    '''
    Decorator for Fluc command

    Parameters
    ----------
    permissions : Optional[:class:`~user.Permissions`]
        Required Fluc permissions to run command, by default :attr:`~user.Permissions.default`
    discord_permissions : Optional[:class:`discord.Permissions`]
        Required Discord server permissions to run command, by default :attr:`discord.Permissions.none`
    keep_message : Optional[bool]
        Whether to keep the message, by default False
    
    Returns
    --------
    Any
        Result of :class:`discord.ext.commands.Command`
    '''
    def decorator(coro: Callable[..., Awaitable[Any]]):
        command = coro.__name__
        command = command.removeprefix('cmd_')

        async def wrapper(ctx: commands.Context, *args, **kwargs):
            if not ctx.guild:
                return
            user = await db.get_user(ctx.author.id)
            if not user:
                if ctx.author in main_server.members:
                    user = User.new(ctx.author.id)
                    await db.add_user(user)
            
            # Restrictions
            try:
                assert user, 'You are not a user'
                # Do not let user run the same command multiple times at once
                assert command not in running[user.id]
            except AssertionError:
                return
            if permissions.elevated:
                assert user.is_elevated, 'You cannot run this command at this time'
            if permissions.auth:
                assert user.auth, 'You must be authorized to use this command. Please login on our [website](https://fluc.lol) to authorize.'
            if permissions.owner:
                assert user.id == db.owner_id, 'You cannot run this command at this time'
            try:
                if not permissions.ignore_user_blacklist:
                    assert not await db.get_user_blacklist(ctx.author.id), 'User blacklisted'
                if not permissions.ignore_server_blacklist:
                    assert not await db.get_server_blacklist(ctx.guild.id), 'Server blacklisted'
            except AssertionError:
                return
            # Check cooldown for non elevated users
            if not user.is_elevated:
                if not command in cooldowns.to_check:
                    cooldowns.to_check[command] = [command]

                now = datetime.now(UTC)
                to_check = cooldowns.to_check[command]
                for cmd in to_check:
                    server_cooldown = cooldowns.cooldowns[cmd][2]
                    user_cooldown = cooldowns.cooldowns[cmd][3]
                    min_members = cooldowns.cooldowns[cmd][4]
                    key = (cmd, ctx.author.id, ctx.channel.id)
                    try:
                        async with locks[ctx.author.id]:
                            await cooldowns.check_cooldown(
                                cmd,
                                ctx.guild.id,
                                ctx.author.id,
                                user_cooldown=user_cooldown,
                                server_cooldown=server_cooldown,
                                now=now,
                                apply_cd=True,
                                user=user
                            )
                    except commands.CommandOnCooldown as exc:
                        if isinstance(ctx.message, discord.Message):
                            if key not in cooldowns.warned_users or cooldowns.warned_users[key] < now.timestamp():
                                await reply(ctx.message, f'Command on cooldown. Retry <t:{int(exc.retry_after + datetime.now(UTC).timestamp())}:R>', 'error', delete_after=exc.retry_after - 0.5)
                                await ctx.message.delete()
                                cooldowns.warned_users[key] = now.timestamp() + exc.retry_after
                            return
                    # Check members AFTER cooldown is checked
                    if min_members:
                        if len(ctx.guild.members) <= min_members:
                            embed = get_embed('This command is not allowed in small servers.', 'warning')
                            if command == 'bypass':
                                # More info about common command
                                embed.description = f'Use `.nuke` instead or watch demo of this command here - {'YouTube video soon'}'
                            return await ctx.send(embed=embed, delete_after=10)
            try:
                if not keep_message:
                    await ctx.message.delete()
            except Exception:
                pass

            invoke_args = [*args]
            annotations = dict(coro.__annotations__)
            # Combine (arg, annotation)
            zipped = zip(invoke_args, list(annotations.values())[2:])
            zipped = [item for item in zipped]

            # Parse arguments
            for i, (value, arg_type) in enumerate(zipped):
                try:
                    invoke_args[i] = utils.parse_arguments(list(annotations.keys())[i + 2], value, arg_type)
                except TypeError as exc:
                    raise commands.BadArgument(str(exc))

            async def execute():
                log.info(f'Command {command} ran by {user.id}')
                if user.is_premium or user.is_elevated:
                    return await coro(*ctx.args)
                return await coro(*ctx.args[:2])

            ctx.args = [ctx, user] + invoke_args
            try:
                running[user.id].add(command)
                try:
                    if user.is_elevated:
                        return await execute()
                    async with global_command_semaphore:
                        async with user_command_semaphore[user.id]:
                            return await execute()
                except discord.HTTPException:
                    pass
            finally:
                running[user.id].remove(command)
                if not running[user.id]:
                    del running[user.id]
        cooldowns.add_command(command, permissions, discord_permissions, wrapper, coro.__doc__)
        return wrapper
    return decorator

async def on_command_error(ctx: commands.Context, exc: discord.ClientException):
    trace_id, trace = str(uuid4()), ''.join(TracebackException.from_exception(exc).format())
    footer = f'Trace ID: {trace_id}'
    utils.set_trace(trace_id, trace) 
    # Skip bc cooldown was not added
    if isinstance(exc, AssertionError):
        return
    log.error(trace)
    try:
        if isinstance(exc, commands.CommandInvokeError):
            await reply(ctx.message, str(exc), 'error', footer=footer)
        elif isinstance(exc, commands.MissingPermissions):
            await reply(ctx.message, str(exc), 'error', footer=footer)
        elif isinstance(exc, (commands.CommandNotFound, commands.CheckFailure)):
            pass
        else:
            await reply(ctx.message, str(exc), 'error', footer=footer)
    except discord.HTTPException:
        return
    
def get_bots() -> Tuple[commands.Bot, commands.Bot, commands.Bot]:
    '''
    Returns all bots

    Returns
    -------
    Tuple[:class:`discord.ext.commands.Bot`, :class:`discord.ext.commands.Bot`, :class:`discord.ext.commands.Bot`]
        nuke bot, manager, no-admin bot
    '''
    return [] # type: ignore

def make_bot_help(bot: commands.Bot) -> HelpMenu:
    '''
    Constructs HelpMenu view

    Will use commands from specified bot

    Parameters
    ----------
    bot : :class:`discord.ext.commands.Bot`
        The bot to describe

    Returns
    -------
    HelpMenu
        :class:`discord.ui.View` ready to be sent
    '''
    fields: list[dict] = []
    for cmd in bot.commands:
        cooldown = cooldowns.callbacks.get(cmd.name)
        if cooldown:
            permissions = cooldown[1]
        else:
            permissions = Permissions()
        # is bro nuking my code# X just keyboard broken. why u kissing me? L rizz.
        doc = utils.parse_doc(cmd, cooldowns)
        fields.append({
            'name': f'📂 {cmd.name}{'*' if permissions.elevated else ''}',
            'value': f'↳ {doc['brief']}',
            'inline': False
        })
    embed = discord.Embed(description=f'Welcome to {p_name} V{__version__}. Support: {website}')
    # Hm? Put this somewhere else
    # embed.set_footer(text='* Command can only be used by admins')
    return HelpMenu(embed, fields)

async def submit_worker(worker: str, code: str):
    session = aiohttp.ClientSession()
    headers = {
        'authorization': config['worker_authorization']
    }
    try:
        await session.post(worker, data=code.encode(), headers=headers)
    finally:
        await session.close()