import discord
import utils
import aiohttp
from discord.utils import MISSING
from typing import Tuple, Mapping
from datetime import datetime
from string import hexdigits
from typing import (
    TypedDict,
    Optional,
    List,
    Union,
    Dict,
    Literal
)

xs32 = utils.Xorshift32()


class OverwriteBackup(TypedDict):
    member: Optional[int]
    role: Optional[int]
    overwrites: Dict[str, bool]


class UnicodeEmojiBackup(TypedDict):
    unicode: str


class EmojiBackup(TypedDict):
    id: int
    name: str
    url: str
    roles: List[int]
    # Discord keeps emojis in the order they were created.
    # Knowing the creation time of emojis allows us
    # to recover their original positions
    created_at: float


class StickerBackup(TypedDict):
    id: int
    name: str
    description: str
    created_at: float
    url: str
    emoji: str


class MessagableBackup(TypedDict):
    id: int
    name: str
    nsfw: bool
    position: int
    category_id: Optional[int]
    slowmode_delay: int
    permissions_synced: bool
    overwrites: List[OverwriteBackup]


class TextChannelBackup(MessagableBackup):
    topic: Optional[str]
    news: bool
    default_auto_archive_duration: int
    default_thread_slowmode_delay: int


class VoiceChannelBackup(MessagableBackup):
    bitrate: int
    rtc_region: Optional[str]
    video_quality_mode: int
    user_limit: int


class ForumChannelTagBackup(TypedDict):
    name: str
    moderatred: bool
    emoji: Optional[Union[EmojiBackup, UnicodeEmojiBackup]]


class ForumChannelBackup(MessagableBackup):
    topic: Optional[str]
    available_tags: List[ForumChannelTagBackup]
    default_layout: int
    default_sort_order: Optional[int]
    default_reaction_emoji: Optional[Union[EmojiBackup, UnicodeEmojiBackup]]
    default_thread_slowmode_delay: int
    default_auto_archive_duration: int


class StageChannelBackup(VoiceChannelBackup):
    topic: Optional[str]


class CategoryBackup(TypedDict):
    id: int
    name: str
    position: int
    overwrites: List[OverwriteBackup]


class ScheduledEventBackup(TypedDict):
    id: int
    name: str
    description: Optional[str]
    channel_id: Optional[int]
    location: Optional[str]
    entitiy_type: int
    privacy_level: int
    end_time: Optional[float]
    start_time: float
    cover_image: Optional[str]
    status: int


class RoleIconBackup(TypedDict):
    asset_type: Literal[0, 1]
    asset: str


class RoleBackup(TypedDict):
    id: int
    name: str
    icon: Optional[RoleIconBackup]
    color: int
    hoist: bool
    mentionable: bool
    bot_id: Optional[int]
    default: bool
    position: int
    permissions: int


class MemberBackup(TypedDict):
    id: int
    nick: Optional[str]
    roles: List[int]
    timed_out_until: Optional[float]


class AutoModTriggerBackup(TypedDict):
    type: int
    presets: Optional[int]
    keyword_filter: Optional[List[str]]
    allow_list: Optional[List[str]]
    mention_limit: Optional[int]
    regex_patterns: Optional[List[str]]
    mention_raid_protection: Optional[bool]


class AutoModActionBackup(TypedDict):
    type: Optional[int]
    duration: Optional[int]
    channel_id: Optional[int]
    custom_message: Optional[str]


class AutoModRuleBackup(TypedDict):
    name: str
    event_type: int
    trigger: AutoModTriggerBackup
    actions: List[AutoModActionBackup]
    enabled: bool
    exempt_role_ids: List[int]
    exempt_channel_ids: List[int]


class SoundboardSoundBackup(TypedDict):
    name: str
    available: bool
    volume: float
    emoji: EmojiBackup
    sound: str


class GuildBackup(TypedDict):
    name: str
    icon: Optional[str]
    banner: Optional[str]
    community: bool
    description: Optional[str]
    vanity_code: Optional[str]
    preferred_locale: str
    premium_progress_bar_enabled: int
    afk_timeout: int
    afk_channel_id: Optional[int]
    rules_channel_id: Optional[int]
    public_updates_channel_id: Optional[int]
    system_channel_id: Optional[int]
    system_channel_flags: int
    invites_paused_until: Optional[float]
    dms_paused_until: Optional[float]
    default_notification: int
    verification_level: int
    explicit_content_filter: int
    splash: Optional[str]
    discovery_splash: Optional[str]
    discoverable: bool
    widget_enabled: bool
    widget_channel_id: Optional[int]


class BackupData(TypedDict):
    members: List[MemberBackup]
    roles: List[RoleBackup]
    text_channels: List[TextChannelBackup]
    voice_channels: List[VoiceChannelBackup]
    stage_channels: List[StageChannelBackup]
    forum_channels: List[ForumChannelBackup]
    categories: List[CategoryBackup]
    soundboard_sounds: List[SoundboardSoundBackup]
    scheduled_events: List[ScheduledEventBackup]
    automod_rules: List[AutoModRuleBackup]
    emojis: List[EmojiBackup]
    stickers: List[StickerBackup]
    guild: GuildBackup


async def create_backup(guild: discord.Guild) -> Tuple[str, BackupData]:
    def parse_overwrites(overwrites: Dict[Union[discord.Role, discord.Member, discord.Object], discord.PermissionOverwrite]) -> List[OverwriteBackup]:
        _overwrites: List[OverwriteBackup] = []
        for key, value in overwrites.items():
            _overwrite: OverwriteBackup = {
                'member': None,
                'role': None,
                'overwrites': {}
            }

            if isinstance(key, discord.Role):
                _overwrite['role'] = key.id

            elif isinstance(key, discord.Member):
                _overwrite['member'] = key.id
            
            else:
                continue
            
            __overwrites = {}
            for permission, flag in value:
                __overwrites[permission] = flag
            _overwrite['overwrites'] = __overwrites
            _overwrites.append(_overwrite)
        return _overwrites

    def parse_asset(asset: Optional[discord.Asset]) -> Optional[str]:
        if not asset:
            return None
        return asset.url

    def parse_role_icon(asset: Optional[Union[discord.Asset, str]]) -> Optional[RoleIconBackup]:
        if not asset:
            return None
        if isinstance(asset, str):
            return { 'asset_type': 0, 'asset': asset }
        return { 'asset_type': 1, 'asset': asset.url }
    
    def parse_guild_emoji(emoji: Optional[Union[discord.PartialEmoji, discord.Emoji]]) -> Optional[EmojiBackup]:
        if not emoji:
            return
        _emoji: EmojiBackup = {
            'id': emoji.id,
            'name': emoji.name,
            'url': emoji.url,
            'created_at': parse_datetime(emoji.created_at), # pyright: ignore[reportArgumentType, reportAssignmentType]
            'roles': []
        }
        if isinstance(emoji, discord.Emoji):
            _emoji['roles'] = [role.id for role in emoji.roles]
        return _emoji

    def parse_emoji(emoji: Optional[Union[discord.PartialEmoji, discord.Emoji]]) -> Optional[Union[EmojiBackup, UnicodeEmojiBackup]]:
        if not emoji:
            return None
        if not emoji.id:
            return { 'unicode': emoji.name }
        else:
            return parse_guild_emoji(emoji)

    def parse_tags(tags: List[discord.ForumTag]) -> List[ForumChannelTagBackup]:
        _tags = []
        for tag in tags:
            _tag: ForumChannelTagBackup = {
                'name': tag.name,
                'moderatred': tag.moderated,
                'emoji': parse_emoji(tag.emoji) if tag.emoji else None
            }
            _tags.append(_tag)
        return _tags

    def parse_datetime(date: Optional[datetime]) -> Optional[float]:
        if not date:
            return None
        return date.timestamp()
    
    def parse_autmod_trigger(trigger: discord.AutoModTrigger) -> AutoModTriggerBackup:
        _trigger: AutoModTriggerBackup = {
            'type': trigger.type.value,
            'presets': trigger.presets.value,
            'keyword_filter': trigger.keyword_filter,
            'allow_list': trigger.allow_list,
            'mention_limit': trigger.mention_limit,
            'regex_patterns': trigger.regex_patterns,
            'mention_raid_protection': trigger.mention_raid_protection
        }
        return _trigger

    is_community = 'COMMUNITY' in guild.features
    data: BackupData = { # pyright: ignore[reportAssignmentType]
        'members': [],
        'roles': [],
        'text_channels': [],
        'voice_channels': [],
        'stage_channels': [],
        'forum_channels': [],
        'categories': [],
        'soundboard_sounds': [],
        'automod_rules': [],
        'scheduled_events': [],
        'stickers': [],
        'emojis': [],
        'guild': {}
    }

    for member in guild.members:
        _member_data: MemberBackup = {
            'id': member.id,
            'nick': member.nick,
            'roles': [role.id for role in member.roles],
            'timed_out_until': parse_datetime(member.timed_out_until) if member.timed_out_until else None
        }
        data['members'].append(_member_data)

    for role in guild.roles:
        bot_id: Optional[int] = None

        if role.is_bot_managed():
            bot_id = role.tags.bot_id # pyright: ignore[reportOptionalMemberAccess]

        _role_data: RoleBackup = {
            'id': role.id,
            'name': role.name,
            'icon': parse_role_icon(role.icon),
            'color': role.color.value,
            'hoist': role.hoist,
            'mentionable': role.mentionable,
            'bot_id': bot_id,
            'default': role.guild.default_role == role,
            'position': role.position,
            'permissions': role.permissions.value
        }
        data['roles'].append(_role_data)
    data['roles'].sort(key=lambda r: (r['position'], r['id']), reverse=True)

    for channel in guild.categories:
        _category_channel_data: CategoryBackup = {
            'id': channel.id,
            'name': channel.name,
            'position': channel.position,
            'overwrites': parse_overwrites(channel.overwrites)
        }
        data['categories'].append(_category_channel_data)

    for channel in guild.text_channels:
        _text_channel_data: TextChannelBackup = {
            'id': channel.id,
            'name': channel.name,
            'nsfw': channel.nsfw,
            'news': channel.is_news(),
            'topic': channel.topic,
            'position': channel.position,
            'category_id': channel.category_id,
            'slowmode_delay': channel.slowmode_delay,
            'default_auto_archive_duration': channel.default_auto_archive_duration,
            'default_thread_slowmode_delay': channel.default_thread_slowmode_delay,
            'permissions_synced': channel.permissions_synced,
            'overwrites': parse_overwrites(channel.overwrites)
        }
        data['text_channels'].append(_text_channel_data)

    for channel in guild.voice_channels:
        _voice_channel_data: VoiceChannelBackup = {
            'id': channel.id,
            'name': channel.name,
            'nsfw': channel.nsfw,
            'position': channel.position,
            'category_id': channel.category_id,
            'slowmode_delay': channel.slowmode_delay,
            'video_quality_mode': channel.video_quality_mode.value,
            'bitrate': channel.bitrate,
            'rtc_region': channel.rtc_region,
            'user_limit': channel.user_limit,
            'overwrites': parse_overwrites(channel.overwrites),
            'permissions_synced': channel.permissions_synced
        }
        data['voice_channels'].append(_voice_channel_data)

    if is_community:
        for channel in guild.stage_channels:
            _stage_channel_data: StageChannelBackup = {
                'id': channel.id,
                'name': channel.name,
                # 'topic': channel.topic,
                'topic': '', # Umm
                'nsfw': channel.nsfw,
                'position': channel.position,
                'category_id': channel.category_id,
                'slowmode_delay': channel.slowmode_delay,
                'video_quality_mode': channel.video_quality_mode.value,
                'bitrate': channel.bitrate,
                'rtc_region': channel.rtc_region,
                'user_limit': channel.user_limit,
                'overwrites': parse_overwrites(channel.overwrites),
                'permissions_synced': channel.permissions_synced
            }
            data['stage_channels'].append(_stage_channel_data)

        for channel in guild.forums:
            _forum_channel_data: ForumChannelBackup = {
                'id': channel.id,
                'name': channel.name,
                'topic': channel.topic,
                'nsfw': channel.nsfw,
                'position': channel.position,
                'category_id': channel.category_id,
                'slowmode_delay': channel.slowmode_delay,
                'available_tags': parse_tags(list(channel.available_tags)),
                'default_auto_archive_duration': channel.default_auto_archive_duration,
                'default_layout': channel.default_layout.value,
                'default_reaction_emoji': parse_emoji(channel.default_reaction_emoji),
                'default_sort_order': channel.default_sort_order.value if channel.default_sort_order else None,
                'default_thread_slowmode_delay': channel.default_thread_slowmode_delay,
                'overwrites': parse_overwrites(channel.overwrites),
                'permissions_synced': channel.permissions_synced
            }
            data['forum_channels'].append(_forum_channel_data)

    for sound in guild.soundboard_sounds:
        _soundboard_sound_data: SoundboardSoundBackup = {
            'name': sound.name,
            'volume': sound.volume,
            'available': sound.available,
            'emoji': parse_emoji(sound.emoji), # pyright: ignore[reportArgumentType, reportAssignmentType]
            'sound': sound.url
        }
        data['soundboard_sounds'].append(_soundboard_sound_data)

    for event in guild.scheduled_events:
        _scheduled_event_data: ScheduledEventBackup = {
            'id': event.id,
            'name': event.name,
            'description': event.description,
            'channel_id': event.channel_id,
            'location': event.location,
            'entitiy_type': event.entity_type.value,
            'privacy_level': event.privacy_level.value,
            'end_time': parse_datetime(event.end_time),
            'start_time': parse_datetime(event.start_time), # pyright: ignore[reportAssignmentType]
            'cover_image': parse_asset(event.cover_image),
            'status': event.status.value
        }
        data['scheduled_events'].append(_scheduled_event_data)

    for rule in await guild.fetch_automod_rules():
        actions: List[AutoModActionBackup] = []
        for action in rule.actions:
            _action: AutoModActionBackup = {
                'type': action.type.value,
                'duration': action.duration.seconds if action.duration else None,
                'channel_id': action.channel_id,
                'custom_message': action.custom_message
            }
            actions.append(_action)

        _automod_rule_data: AutoModRuleBackup = {
            'enabled': rule.enabled,
            'event_type': rule.event_type.value,
            'exempt_channel_ids': list(rule.exempt_channel_ids),
            'exempt_role_ids': list(rule.exempt_role_ids),
            'name': rule.name,
            'trigger': parse_autmod_trigger(rule.trigger),
            'actions': actions
        }
        data['automod_rules'].append(_automod_rule_data)

    for sticker in guild.stickers:
        _sticker: StickerBackup = {
            'id': sticker.id,
            'name': sticker.name,
            'description': sticker.description,
            'url': sticker.url,
            'created_at': sticker.created_at.timestamp(),
            'emoji': sticker.emoji
        }
        data['stickers'].append(_sticker)

    for emoji in guild.emojis:
        _emoji = parse_guild_emoji(emoji)
        if _emoji:
            data['emojis'].append(_emoji)

    data['guild'] = {
        'name': guild.name,
        'icon': parse_asset(guild.icon),
        'banner': parse_asset(guild.banner),
        'community': is_community,
        'description': guild.description,
        'vanity_code': guild.vanity_url_code,
        'preferred_locale': guild.preferred_locale.name,
        'premium_progress_bar_enabled': guild.premium_progress_bar_enabled,
        'afk_timeout': guild.afk_timeout,
        'afk_channel_id': guild._afk_channel_id,
        'public_updates_channel_id': guild._public_updates_channel_id,
        'rules_channel_id': guild._rules_channel_id,
        'system_channel_id': guild._system_channel_id,
        'system_channel_flags': guild.system_channel_flags.value,
        'invites_paused_until': parse_datetime(guild.invites_paused_until),
        'dms_paused_until': parse_datetime(guild.dms_paused_until),
        'default_notification': guild.default_notifications.value,
        'verification_level': guild.verification_level.value,
        'explicit_content_filter': guild.explicit_content_filter.value,
        'splash': parse_asset(guild.splash),
        'discovery_splash': parse_asset(guild.discovery_splash),
        'discoverable': 'DISCOVERABLE' in guild.features,
        'widget_enabled': guild.widget_enabled,
        'widget_channel_id': guild._widget_channel_id
    }

    key = ''.join(xs32.choice(hexdigits, length=32))
    key = [key[i:i+4] for i in range(0, len(key), 4)]
    key = '-'.join(key)
    return key, data

async def load_backup(guild: discord.Guild, backup: BackupData) -> bool:
    def parse_overwrites(overwrites: List[OverwriteBackup]) -> Mapping[Union[discord.Role, discord.Member, discord.Object], discord.PermissionOverwrite]:
        _overwrites = {}
        for overwrite in overwrites:
            obj = None
            member = overwrite['member']
            role = overwrite['role']
            if member:
                obj = guild.get_member(member)
            elif role:
                obj = guild.get_role(role)
            if obj:
                _overwrites[obj] = discord.PermissionOverwrite(**overwrite['overwrites'])
        return _overwrites
    
    def parse_emoji(emoji: Optional[Union[EmojiBackup, UnicodeEmojiBackup]]) -> Optional[Union[discord.Emoji, discord.PartialEmoji, str]]:
        if not emoji:
            return
        if not emoji.get('id'):
            # Unicode
            return emoji.get('unicode')
        return ids[emoji.get('id')]
    
    def parse_tags(tags: List[ForumChannelTagBackup]) -> List[discord.ForumTag]:
        _tags = []
        for tag in tags:
            _tags.append(discord.ForumTag(
                name=tag['name'],
                moderated=tag['moderatred'],
                emoji=parse_emoji(tag['emoji'])
            ))
        return _tags

    if not guild.me.guild_permissions.administrator:
        return False
    
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(3))
    tasks = len(backup)
    ids = {}
    features = guild.features
    temp = await guild.create_text_channel('temp')
    await temp.send('Loading backup...')
    await temp.send(f'[1/{tasks}] Loading roles...')
    bot_roles = []
    for role in backup['roles']:
        kwargs = {
            'name': role['name'],
            'color': discord.Color(role['color']),
            'hoist': role['hoist'],
            'mentionable': role['mentionable'],
            'permissions': discord.Permissions(role['permissions'])
        }
        if 'ROLE_ICON' in features:
            icon = role['icon']
            if icon:
                if icon['asset_type'] == 0:
                    kwargs['display_icon'] = icon['asset']
                else:
                    try:
                        async with session.get(icon['asset']) as response:
                            content = await response.content.read()
                            if content and response.ok:
                                kwargs['display_icon'] = content
                    except aiohttp.ClientResponseError:
                        pass
        _role = None
        
        bot_id = role['bot_id']
        if bot_id:
            bot_roles.append((bot_id, kwargs))
        else:
            _role = await guild.create_role(**kwargs)
            ids[role['id']] = _role

    for bot_id, kwargs in bot_roles:
        bot = guild.get_member(bot_id)
        if not bot:
            continue
        for bot_role in bot.roles:
            if bot_role.tags and bot_role.tags.bot_id == bot.id:
                await bot_role.edit(**kwargs)
    del bot_roles

    await temp.send(f'[2/{tasks}] Loading emojis, stickers, soundboards...')
    backup['emojis'].sort(key=lambda e: e['created_at'])
    for emoji in backup['emojis']:
        image: bytes
        try:
            async with session.get(emoji['url']) as response:
                content = await response.content.read()
                if not content or not response.ok:
                    continue
                image = content
        except aiohttp.ClientResponseError:
            continue
        
        roles = []
        for item_id, item in ids.items():
            if item_id in emoji['roles']:
                roles.append(item)
        _emoji = await guild.create_custom_emoji(
            name=emoji['name'],
            roles=roles,
            image=image
        )
        ids[emoji['id']] = _emoji

    backup['stickers'].sort(key=lambda e: e['created_at'])
    for sticker in backup['stickers']:
        image: bytes
        try:
            async with session.get(sticker['url']) as response:
                content = await response.content.read()
                if not content or not response.ok:
                    continue
                image = content
        except aiohttp.ClientResponseError:
            continue
        _sticker = await guild.create_sticker(
            name=sticker['name'],
            description=sticker['description'],
            emoji=sticker['emoji'],
            file=discord.File(image)
        )
        ids[sticker['id']] = _sticker
    
    t1 = None
    t2 = None
    if backup['guild']['community'] or any(channel['news'] for channel in backup['text_channels']):
        t1 = await guild.create_text_channel('t1')
        t2 = await guild.create_text_channel('t2')
        await guild.edit(
            community=True,
            rules_channel=t1,
            public_updates_channel=t2,
            explicit_content_filter=discord.ContentFilter.all_members,
            verification_level=discord.VerificationLevel.medium
        )

    await temp.send(f'[3/{tasks}] Loading channels...')
    for category_channel in backup['categories']:
        _category_channel = await guild.create_category(
            name=category_channel['name'],
            overwrites=parse_overwrites(category_channel['overwrites'])
        )
        ids[category_channel['id']] = _category_channel
    
    for text_channel in backup['text_channels']:
        _category = ids.get(text_channel['category_id'])
        _text_channel = await guild.create_text_channel(
            name=text_channel['name'],
            category=_category,
            topic=text_channel['topic'] or MISSING,
            news=text_channel['news'],
            slowmode_delay=text_channel['slowmode_delay'],
            default_auto_archive_duration=text_channel['default_auto_archive_duration'],
            overwrites=parse_overwrites(text_channel['overwrites'])
        )
        permissions_synced = text_channel['permissions_synced']
        if permissions_synced:
            await _text_channel.edit(sync_permissions=permissions_synced)
        ids[text_channel['id']] = _text_channel

    for voice_channel in backup['voice_channels']:
        _category = ids.get(voice_channel['category_id'])
        _voice_channel = await guild.create_voice_channel(
            name=voice_channel['name'],
            nsfw=voice_channel['nsfw'],
            category=_category,
            video_quality_mode=discord.VideoQualityMode(voice_channel['video_quality_mode']),
            bitrate=voice_channel['bitrate'],
            rtc_region=voice_channel['rtc_region'],
            user_limit=voice_channel['user_limit'],
            overwrites=parse_overwrites(voice_channel['overwrites'])
        )
        await _voice_channel.edit(
            slowmode_delay=voice_channel['slowmode_delay'],
            sync_permissions=voice_channel['permissions_synced']
        )
        ids[voice_channel['id']] = _voice_channel

    for stage_channel in backup['stage_channels']:
        _category = ids.get(stage_channel['category_id'])
        _stage_channel = await guild.create_stage_channel(
            name=stage_channel['name'],
            nsfw=stage_channel['nsfw'],
            category=_category,
            video_quality_mode=discord.VideoQualityMode(stage_channel['video_quality_mode']),
            bitrate=stage_channel['bitrate'],
            rtc_region=stage_channel['rtc_region'],
            user_limit=stage_channel['user_limit'],
            overwrites=parse_overwrites(stage_channel['overwrites']),
            position=stage_channel['position']
        )
        await _stage_channel.edit(
            slowmode_delay=stage_channel['slowmode_delay'],
            sync_permissions=stage_channel['permissions_synced']
        )
        ids[stage_channel['id']] = _stage_channel

    for forum_channel in backup['forum_channels']:
        _category = ids.get(forum_channel['category_id'])
        _forum_channel = await guild.create_forum(
            name=forum_channel['name'],
            topic=forum_channel['topic'] or '',
            nsfw=forum_channel['nsfw'],
            position=forum_channel['position'],
            category=_category,
            slowmode_delay=forum_channel['slowmode_delay'],
            available_tags=parse_tags(forum_channel['available_tags'])
        )
        ids[forum_channel['id']] = _forum_channel

    await temp.send(f'[3/{tasks}] Loading secuirty rules & server information & appearance')
    # for rule in backup['automod_rules']:
    #     await guild.create_automod_rule()
    # TODO

    for scheduled_event in backup['scheduled_events']:
        channel = ids.get(scheduled_event['channel_id'])
        if not channel:
            continue

        cover_image = scheduled_event['cover_image']
        image: bytes = MISSING
        if cover_image:
            try:
                async with session.get(cover_image) as response:
                    content = await response.content.read()
                    if content and response.ok:
                        image = content
            except aiohttp.ClientResponseError:
                continue

        _scheduled_event: discord.ScheduledEvent = await guild.create_scheduled_event( # pyright: ignore[reportCallIssue]
            name=scheduled_event['name'],
            description=scheduled_event['description'],
            channel=channel,
            location=scheduled_event['location'] or '',
            entity_type=discord.EntityType(scheduled_event['entitiy_type']),
            privacy_level=discord.PrivacyLevel(scheduled_event['privacy_level']),
            end_time=utils.optional(datetime.fromtimestamp, scheduled_event['privacy_level'], default=MISSING),
            start_time=datetime.fromtimestamp(scheduled_event['start_time']),
            image=image
        )
        ids[scheduled_event['id']] = _scheduled_event
    return True