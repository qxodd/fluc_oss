import discord
import logging
import orjson
import shared
import asyncio
import utils
import platform
import pydactyl
import psutil
import binlog
from shutil import disk_usage
from noadmin import bot as noadmin
from api import get_roles
from host import Service as DatalixService
from typing import Union, Optional
from shared import reply, get_embed
from components import InviteButton, DmButton, InviteNoadminButton, ServerMenu
from default import check, cross, p_name
from settings import Set
from db import Db
from user import User, Permissions, Settings
from discord import app_commands
from discord.ext import commands
from discord.ext.tasks import loop
from about import __version__
from collections import defaultdict

log = logging.getLogger(__name__)
bot = commands.Bot(command_prefix='.', intents=discord.Intents.all(), help_command=None)
config = shared.config
db = shared.db
main_server: discord.Guild
cooldowns = shared.cooldowns
command = shared.command
queue = defaultdict(asyncio.Queue)
bot.event(shared.on_command_error)

with open('config/roles.json') as file:
    roles: dict = orjson.loads(file.read())

with open('config/sql.json') as file:
    sql_config: dict = orjson.loads(file.read())

with open('config/tags.json') as file:
    forum_tags: dict = orjson.loads(file.read())

async def get_server_menu() -> ServerMenu:
    nuke = shared.get_bots()[0]
    fields = []
    for guild in nuke.guilds:
        invite = guild.vanity_url
        fields.append({
            'name': guild.name,
            'value': f'ID: {guild.id}\nMembers: {guild.member_count}\nInvite: {invite}',
            'inline': False
        })
    embed = discord.Embed(title='Servers')
    return ServerMenu(embed, fields)

async def verify_member(member: discord.Member):
    await asyncio.sleep(1)
    user = await db.get_user(member.id)
    if not config['enable_verify']:
        assign_ids = [role.id for role in member.roles if not role.id in roles.values()]
        # hidden role
        if 1475527811476230348 not in assign_ids:
            assign_ids += [roles['community']]
        if user:
            if user.is_premium:
                assign_ids.append(roles['premium'])
            if user.is_super:
                assign_ids.append(roles['moderator'])
        if await db.get_user_blacklist(member.id):
            assign_ids = [roles['blacklist']]
        assign_ids = set(assign_ids)
        if assign_ids != {role.id for role in member.roles}:
            update = [role for role in member.guild.roles if role.id in assign_ids]
            await member.edit(roles=update)
    
    elif user:
        auth = user.auth
        if not member == member.guild.me:
            current = {role.id for role in member.roles}
            remove = {
                role_id for name, role_id in roles.items()
                if name != 'mute'
            }
            new = [
                role for role in member.roles
                if role.id not in remove
            ]
            if not auth or auth.expires_in < 0:
                if not current.intersection(remove):
                    return
                try:
                    await member.edit(roles=new)
                except discord.HTTPException:
                    return
            else:
                user_roles = set(get_roles(user))
                if user_roles != current:
                    try:
                        update = [role for role in member.guild.roles if role.id in user_roles]
                        await member.edit(roles=update)
                    except discord.HTTPException:
                        return

@bot.event
async def on_ready():
    assert bot.user
    global main_server
    bot.add_view(DmButton(0))
    main_server = bot.get_guild(config['server_id']) # type: ignore
    if not main_server:
        log.critical(f'Main server not found. Add me via: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot')
        while not main_server:
            await asyncio.sleep(1)
            main_server = bot.get_guild(config['server_id'])
    shared.main_server = main_server
    while not noadmin.user:
        log.info('Waiting for no-admin startup ...')
        await asyncio.sleep(1)
    while not len(shared.get_bots()):
        log.info('Waiting for nuke bot startup ...')
        await asyncio.sleep(1)
    nuke = shared.get_bots()[0]
    assert nuke.user
    loop = asyncio.get_running_loop()
    await bot.add_cog(Set())
    await bot.add_cog(Db(bot))
    bot.add_view(InviteNoadminButton(noadmin.user.id))
    bot.add_view(InviteButton(nuke.user.id))
    bot.add_view(shared.make_bot_help(nuke))
    bot.add_view(await get_server_menu())
    loop.create_task(binlog.run(loop, sql_config, True))
    log.info(f'Logged on {bot.user} (ID: {bot.user.id})')
    # await bot.tree.sync()

@bot.event
async def on_member_join(member: discord.Member):
    await verify_member(member)
    channel = discord.utils.get(member.guild.channels, name='chat')
    name = member.display_name
    name = name.encode().decode('ascii', 'ignore')
    name = name.lstrip('!')
    if name != member.display_name:
        if len(name) > 2:
            await member.edit(nick=name)
        else:
            await member.edit(nick=member.name)
    if isinstance(channel, discord.TextChannel):
        await channel.send(f'Welcome to {p_name} V{__version__} {member.mention}. Invite nake bot: <#{config['invite_channel']}>')

@bot.event
async def on_member_update(_, after: discord.Member):
    await verify_member(after)
    name = after.display_name
    name = name.encode().decode('ascii', 'ignore')
    name = name.lstrip('!')
    if name != after.display_name:
        if len(name) > 2:
            await after.edit(nick=name)
        else:
            await after.edit(nick=after.name)

@bot.event
async def on_message(message: discord.Message):
    if message.channel.id == 1503084994778894367:
        if message.author != bot.user:
            rules_message = await message.channel.send('''
Vouch formats:
1.
    +rep [product] [optional review]
    -rep [product] [optional review]

2.
    vouch @user [product] [optional review]
    scam vouch @user [product] [optional review]
                                
e.g
    +rep @bxod custom bot good communication

:warning: Bad formatted vouches shall get deleted :warning:
:bangbang: Upload attachment of proof if you can :bangbang:
            ''')
            async for message in message.channel.history(limit=100):
                if message.author == bot.user:
                    if not message.id == rules_message.id:
                        await message.delete()
                        break
    await bot.process_commands(message)
        
@bot.command('help', aliases=['h'])
@command(keep_message=True)
@cooldowns.check(3, server_cooldown=True)
async def cmd_help(ctx: commands.Context, user: User, command: Optional[str] = None, *_):
    bot = shared.get_bots()[0]
    '''
    %0
    Shows all commands and info about them
    %2
    - command: Optional
        - If you specify this argument the bot will give you detailed info about the specified command
    '''
    if command:
        cmd = bot.get_command(command)
        if not cmd:
            return await reply(ctx.message, f'The command "{command}" was not found!', 'error')
        doc = utils.parse_doc(cmd, cooldowns)
        server_cooldown = cooldowns.cooldowns[cmd.name][0]
        user_cooldown = cooldowns.cooldowns[cmd.name][1]
        info = (
            f'Aliases: `{'` `'.join(cmd.aliases)}`\n'
            f'Server Cooldown: `{str(server_cooldown) + 's' if server_cooldown else 'Not enabled'}`\n'
            f'User Cooldown: `{str(user_cooldown) + 's' if user_cooldown else 'Not enabled'}`\n'
        )
        embed = discord.Embed(
            title=cmd.name,
            description=doc['brief']
        )
        embed.add_field(name='Information', value=info)
        embed.add_field(name='Description', value=doc['doc'], inline=False)
        embed.add_field(name='Options', value=doc['options'], inline=False)
        return await ctx.reply(embed=embed)
    # yo so what help you want?
    #  i dont want help i need help to unban from serverssss
    # any help for not vibdecodeing..? 
    # give ideas for comannds
    #feet for unban. 🦶
    # unbanned. 💀
    view = shared.make_bot_help(bot)
    await ctx.reply(
        embed=view.embed,
        view=view
    )

@bot.command('stats', aliases=['ping'])
@command(keep_message=True)
@cooldowns.check(1)
async def cmd_stats(ctx: commands.Context, user: User, *args):
    embed = discord.Embed(title=f'{p_name} V{__version__}')
    version = discord.version_info
    embed.add_field(
        name='Connection',
        value=(
            f'Client latency: {round(bot.latency * 1000, 2)}ms\n'
            f'Discord API version: 10\n'
        )
    )
    disk = disk_usage('./')
    memory = psutil.virtual_memory()
    used = utils.convert_bytes(disk.used)
    total = utils.convert_bytes(disk.total)
    memory_used = utils.convert_bytes(memory.used)
    memory_total = utils.convert_bytes(memory.available)
    embed.add_field(
        name='Stats',
        value=(
            f'Memory Usage: {round(memory_used[0], 2)}{memory_used[1]}/{round(memory_total[0], 2)}{memory_total[1]}\n'
            f'Disk Usage: {round(used[0], 2)}{used[1]}/{round(total[0], 2)}{total[1]}'
        )
    )
    embed.add_field(
        name='System',
        value=(
            f'Platform: {platform.platform()}\n'
            f'Python version: {platform.python_version()}\n'
            f'Discord.py version: {version.major}.{version.minor}.{version.micro} {version.releaselevel}'
        ),
        inline=False
    )
    await ctx.reply(embed=embed)

@bot.command('check')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_check(ctx: commands.Context, user_: User, subject: Union[str, int], *args):
    def yn(value: bool):
        return check if value else cross

    assert ctx.guild
    user = None
    if isinstance(subject, int):
        user = await db.get_user(subject)
    if not user:
        member = discord.utils.get(ctx.guild.members, name=subject)
        if member:
            user = await db.get_user(member.id)
    if not user:
        return await reply(ctx.message, f'Member "{subject}" not found', 'warning')
    member_ = discord.utils.get(ctx.guild.members, id=user.id)
    name = None
    if member_:
        name = member_.name
    else:
        if user.auth:
            name = user.auth.username
        else:
            name = subject
    embed = discord.Embed(
        title=f'Info about {name}',
        description=f'ID: {user.id}'
    )
    if member_:
        if member_.avatar:
            embed.set_thumbnail(url=member_.avatar.url)
        else:
            embed.set_thumbnail(url=member_.default_avatar.url)
        if member_.banner:
            embed.set_image(url=member_.banner.url)
    embed.add_field(name='Info', value=(
        f'<:crown:1480917537389543485> Owner: {yn(user.is_owner)}\n'
        f'<:star:1475461823028396042> Super Privileges: {yn(user.is_elevated)}\n'
        f'<:booster:1475459072475004938> Premium: {yn(user.is_premium)}\n'
        f'<:ban:1480902776434458656> Blacklisted: {yn(user.is_blacklisted)}'
    ))
    await ctx.reply(embed=embed)

@bot.command('reinvite')
@command(Permissions(elevated_only=True))
@cooldowns.check(1)
async def cmd_reinvite(ctx: commands.Context, user: User):
    bot = shared.get_bots()[0]
    assert bot.user
    bot_id = bot.user.id
    await ctx.send(embed=InviteButton.embed(), view=InviteButton(bot_id))

@bot.command('reinvite_noadmin')
@command(Permissions(elevated_only=True))
@cooldowns.check(1)
async def cmd_reinvite_noadmin(ctx: commands.Context, user: User):
    assert noadmin.user
    await ctx.send(embed=InviteNoadminButton.embed(), view=InviteNoadminButton(noadmin.user.id))

@bot.command('shutdown')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_shutdown(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx.message, 'All bots scheduled for shutdown...', 'info')
    else:
        return await reply(ctx.message, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'stop')
        if response:
            await reply(ctx.message, 'Failed to shutdown server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.shutdown()

@bot.command('reboot', aliases=['restart'])
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_reboot(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx.message, 'All bots scheduled for restart...', 'info')
    else:
        return await reply(ctx.message, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'restart')
        if response:
            await reply(ctx.message, 'Failed to reboot server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.restart()

@bot.command('kill')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_kill(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx.message, 'Killing all bots...', 'info')
    else:
        return await reply(ctx.message, 'No host specified', 'warning')
    if isinstance(shared.dactyl, pydactyl.async_api_client.AsyncClientAPI):
        response = await shared.dactyl.servers.send_power_action(shared.server, 'kill')
        if response:
            await reply(ctx.message, 'Failed to kill server', 'error')
    elif isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.shutdown()

@bot.command('create_backup')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_create_backup(ctx: commands.Context, user: User):
    if shared.has_host:
        await reply(ctx.message, 'Creating backup...', 'info')
    else:
        return await reply(ctx.message, 'No host specified', 'warning')
    if isinstance(shared.datalix_service, DatalixService):
        await shared.datalix_service.create_backups()
        await reply(ctx.message, 'Successfully created backup', 'info')
    else:
        await reply(ctx.message, 'Invalid host. Could not create backup', 'warning')

@bot.command('view_trace')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(0)
async def cmd_view_trace(ctx: commands.Context, user: User, trace_id: str):
    with open('data/trace.json', 'rb') as file:
        traces = orjson.loads(file.read())
    
    trace = traces.get(trace_id)
    if not trace:
        return await reply(ctx.message, f'Trace with id {trace_id} not found', 'warning')

    for i in range(0, len(trace), 4000):
        for part in trace[i:i+4000]:
            fields = [{
                'name': 'Data',
                'value': part,
                'inline': False
            }]
            await reply(ctx.message, f'Part {i} of {len(trace) // 4000}', fields=fields)

@bot.command('blacklist')
@command(Permissions(elevated_only=True))
@cooldowns.check(0)
async def cmd_blacklist(ctx: commands.Context, user: User, subject: int, type_: str = 'user'):
    assert ctx.guild
    if type_ == 'user':
        if await db.add_user_blacklist(subject):
            member = main_server.get_member(subject)
            if member:
                try:
                    embed = get_embed('You have been blacklisted from Fluc', 'warning')
                    await member.send(embed=embed)
                except discord.HTTPException:
                    pass
            return await reply(ctx.message, f'User with ID {subject} blacklisted')
        await reply(ctx.message, f'User with ID {subject} not blacklisted')
    if type_ == 'server':
        if await db.add_server_blacklist(subject):
            return await reply(ctx.message, f'Sever with ID {subject} blacklisted')
        await reply(ctx.message, f'Sever with ID {subject} not blacklisted')

# @bot.tree.command(name='setautonake')
# @app_commands.describe(delay = 'Delay for auto nake. Skip or set to -1 to disable auto nake.')
# async def cmd_set_autonuke(interaction: discord.Interaction, delay: Optional[int]):
#     user = await db.get_user(interaction.user.id)
#     if not user:
#         user = User.new(interaction.user.id)
#         await db.add_user(user)
#     settings = user._settings
#     if not user:
#         user = User.new(interaction.user.id)
#         await db.add_user(user)
#     if settings is None:
#         settings = {}
#     master = settings.setdefault('master', {})
#     if max(delay if delay is not None else -1, -1) == -1:
#         if master.get('auto_nuke'):
#             del master['auto_nuke']
#     else:
#         master['auto_nuke'] = max(-1, delay if delay is not None else -1)
#     new_settings = Settings(settings)
#     print(new_settings._data)
#     if await db.update_settings(user.id, new_settings):
#         embed = get_embed('Settings updated')
#         return await interaction.response.send_message(embed=embed)
#     embed = get_embed('Settings not updated')
#     await interaction.response.send_message(embed=embed)

# @bot.tree.command(name='selectpreset')
# @app_commands.describe(preset = 'Index of the preset you want to select. Skip or set index to 0 to randomize it every time.')
# async def cmd_select_preset(interaction: discord.Interaction, preset: Optional[int]):
#     user = await db.get_user(interaction.user.id)
#     if not user:
#         user = User.new(interaction.user.id)
#         await db.add_user(user)
#     if not preset:
#         del user.settings._data['selected_preset']
#     else:
#         presets = len(user.settings.presets)
#         if preset > presets:
#             embed = get_embed(f'You can\'t select preset {preset}, because you have only {presets} preset{'s' if presets > 1 else ''}', 'warning')
#             return await interaction.response.send_message(embed=embed)
#         user.settings._data['selected_preset'] = preset
#     if await db.update_settings(user.id, user.settings):
#         embed = get_embed('Settings updated')
#         return await interaction.response.send_message(embed=embed)
#     embed = get_embed('Settings not updated')
#     await interaction.response.send_message(embed=embed)

@bot.command('servers', aliases=['guilds'])
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_servers(ctx: commands.Context, user: User):
    view = await get_server_menu()
    await ctx.reply(embed=view.embed, view=view)

@bot.command('invite', aliases=['inv'])
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)

async def cmd_invite(ctx: commands.Context, user: User, server_id: int):
    nuke = shared.get_bots()[0]
    guild = nuke.get_guild(int(server_id))
    invite = None
    if guild:
        invite = guild.vanity_url
        if not invite:
            for _invite in await guild.invites():
                invite = _invite.url
                break
        if not invite and len(guild.channels):
            try:
                _invite = await guild.channels[0].create_invite()
                invite = _invite.url
            except discord.HTTPException:
                pass
        if guild.invites_paused():
            try:
                await guild.edit(invites_disabled=False)
            except discord.HTTPException as exc:
                await ctx.reply(str(exc))
        await ctx.reply(invite)
    else:
        await ctx.reply('Server not found')

@bot.command('leave')
@command(Permissions(elevated_only=True), keep_message=True)
@cooldowns.check(1)
async def cmd_leave(ctx: commands.Context, user: User, server_id: int):
    nuke = shared.get_bots()[0]
    guild = nuke.get_guild(int(server_id))
    if guild:
        await guild.leave()
        await ctx.reply(f'The bot has left {guild.name} (ID: {guild.id})')
    else:
        await ctx.reply('Server not found')


async def edit_tags(
    channel: discord.Thread,
    tag_type: int,
    tag_name: str,
    moderator: discord.Member,
    reason: Optional[str] = None
):
    if not isinstance(channel, discord.Thread):
        return
    if not isinstance(channel.parent, discord.ForumChannel):
        return
    if not reason:
        reason = 'No reason specified.'
    if not reason.endswith('.'):
        reason += '.'
    tags = channel.parent.available_tags
    applied = channel.applied_tags
    target: discord.ForumTag
    for tag in tags:
        if tag.name == tag_name:
            target = tag
            break
    for tag in tags[:]:
        _tag = forum_tags[tag.name]
        if _tag[1] == tag_type:
            if tag in applied:
                applied.remove(tag)
    applied.append(target) # type: ignore
    await channel.edit(
        applied_tags=applied,
        locked=bool(tag_type)
    )
    if tag_type:
        await channel.send(
            f'Thread locked and marked as **{tag_name}**.\n'
            f'{moderator.name} (ID: {moderator.id}): {reason}'
        )
    else:
        await channel.send(
            f'Updated thread type to **{tag_name}**'
        )

@bot.command('complete')
@commands.has_permissions(manage_threads=True)
async def cmd_complete(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 1, 'completed', ctx.author, reason) # type: ignore

@bot.command('deny')
@commands.has_permissions(manage_threads=True)
async def cmd_deny(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 1, 'denied', ctx.author, reason,) # type: ignore

@bot.command('pend')
@commands.has_permissions(manage_threads=True)
async def cmd_pend(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 1, 'pending', ctx.author, reason) # type: ignore

@bot.command('close')
@commands.has_permissions(manage_threads=True)
async def cmd_close(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 1, 'closed', ctx.author, reason) # type: ignore

@bot.command('type_support')
@commands.has_permissions(manage_threads=True)
async def cmd_type_support(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 0, 'support', ctx.author, reason) # type: ignore

@bot.command('type_complain')
@commands.has_permissions(manage_threads=True)
async def cmd_type_complain(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 0, 'complain', ctx.author, reason) # type: ignore

@bot.command('type_suggestion')
@commands.has_permissions(manage_threads=True)
async def cmd_type_suggestion(ctx: commands.Context, *, reason: Optional[str] = None):
    await edit_tags(ctx.channel, 0, 'suggestion', ctx.author, reason) # type: ignore
