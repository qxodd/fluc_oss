import asyncio
import aiohttp
import shared
import orjson
import time
import pymysql
import threading
from random import randint
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication import row_event
from user import User, AuthData, Settings
from typing import Union, Optional

with open('config/sql.json', 'rb') as file:
    sql_config = orjson.loads(file.read())
with open('config/config.json', 'rb') as file:
    config = orjson.loads(file.read())
with open('config/roles.json', 'rb') as file:
    role_config = orjson.loads(file.read())

def get_roles(user: User) -> list[int]:
    roles = []
    if not user.is_blacklisted:
        roles.append(role_config['community'])
        # if not user.verified:
        #     roles.append(role_config['mute'])
        if user.is_super:
            roles.append(role_config['moderator'])
        if user.is_premium:
            roles.append(role_config['premium'])
    else:
        roles.append(role_config['blacklist'])
    return roles

async def update_roles(user: User, session: aiohttp.ClientSession) -> Optional[aiohttp.ClientResponse]:
    desired_roles = get_roles(user)
    if not desired_roles:
        return None
    async with session.get(f'/api/v10/guilds/{config['server_id']}/members/{user.id}') as response:
        if not response.ok:
            return None
        member_data = await response.json()
        current_roles = set(int(role) for role in member_data.get('roles', []))
    managed_roles = set(role_config.values())
    desired_roles = set(desired_roles)
    to_keep = current_roles - managed_roles
    to_add = desired_roles - set(role for role in current_roles if role not in managed_roles)
    all_roles = to_keep | to_add
    return await session.patch(f'/api/v10/guilds/{config['server_id']}/members/{user.id}', json={'roles': list(all_roles)})


start_ts: float
db = shared.db
stop = threading.Event()
t_event = Union[
    row_event.WriteRowsEvent,
    row_event.DeleteRowsEvent,
    row_event.UpdateRowsEvent
]

def reader(loop: asyncio.AbstractEventLoop, sql: dict, queue: asyncio.Queue):
    global start_ts
    start_ts = time.time()
    _sql = sql.copy()
    server_id = _sql.pop('server', 0)
    unique = randint(1, 2147483547)
    server_id = unique if server_id != unique else unique + randint(1, 100)
    
    # Get log file IMPORTANT cuz will cause loops
    conn = pymysql.connect(**_sql)
    cursor = conn.cursor()
    cursor.execute('SHOW MASTER STATUS')
    result = cursor.fetchone()
    log_file, log_pos = result[0], result[1]
    cursor.close()
    conn.close()
    stream = BinLogStreamReader(
        connection_settings=_sql,
        blocking=True,
        only_events=[
            row_event.WriteRowsEvent,
            row_event.UpdateRowsEvent,
            row_event.DeleteRowsEvent
        ],
        only_tables=[
            'supers',
            'premium',
            'user_blacklist',
            'server_blacklist',
            'users',
            'auths',
            'settings'
        ],
        server_id=server_id,
        log_file=log_file,
        log_pos=log_pos
    )
    
    try:
        event = stream.fetchone()
        if stop.is_set():
            return
        if event:
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        time.sleep(1)
    finally:
        stream.close()

async def run(loop: asyncio.AbstractEventLoop, sql: dict, update: Optional[bool] = False):
    queue = asyncio.Queue()
    loop.run_in_executor(None, reader, loop, sql, queue)
    session = aiohttp.ClientSession('https://discord.com')
    headers = {
        'Authorization': f'Bot {config['manager']}',
        'Content-Type': 'application/json'
    }
    session.headers.update(headers)
    try:
        while True:
            event: t_event = await queue.get()
            if event.timestamp < start_ts:
                continue
            if not event.rows:
                continue
            for row in event.rows:
                table = event.table
                if isinstance(event, row_event.UpdateRowsEvent):
                    row = row['after_values']
                    match table:
                        case 'users':
                            user = await db._cache.get_user(row['id'])
                            if user:
                                user._data.update(row)
                                if update:
                                    await update_roles(user, session)
                        case 'auths':
                            user = await db.get_user(row['id'])
                            auth = await db._cache.get_auth(row['id'])
                            if auth:
                                auth._data.update(row)
                        case 'settings':
                            user = await db._cache.get_user(row['id'])
                            if user:
                                decoded = orjson.loads(row['data'])
                                if user._settings:
                                    user._settings.update(decoded)
                                else:
                                    user._settings = decoded
                else:
                    row = row['values']
                if isinstance(event, row_event.WriteRowsEvent):
                    match table:
                        case 'supers':
                            user = await db.get_user(row['id'])
                            await db._cache.add_super(row['id'], row['expires'])
                            if user and update:
                                await update_roles(user, session)
                        case 'premium':
                            user = await db.get_user(row['id'])
                            await db._cache.add_premium(row['id'], row['expires'] or None)
                            if user and update:
                                await update_roles(user, session)
                        case 'user_blacklist':
                            user = await db.get_user(row['id'])
                            await db._cache.add_user_blacklist(row['id'], row['expires'])
                            if user and update:
                                await update_roles(user, session)
                        case 'server_blacklist':
                            user = await db.get_user(row['id'])
                            await db._cache.add_server_blacklist(row['id'], row['expires'])
                            if user and update:
                                await update_roles(user, session)
                        case 'users':
                            user = User.new(
                                row['id'],
                                server_amount=row['server_amount'],
                                user_amount=row['user_amount'],
                                verified=row['verified']
                            )
                            await db._cache.add_user(user)
                        case 'auths':
                            auth = AuthData(row)
                            await db._cache.add_auth(auth)
                        case 'settings':
                            user = await db._cache.get_user(row['id'])
                            if user:
                                user.settings._data = Settings(row)._data
                elif isinstance(event, row_event.DeleteRowsEvent):
                    user = await db.get_user(row['id'])
                    match table:
                        case 'supers':
                            await db._cache.remove_super(row['id'])
                            if user and update:
                                await update_roles(user, session)
                        case 'premium':
                            await db._cache.remove_premium(row['id'])
                            if user and update:
                                await update_roles(user, session)
                        case 'user_blacklist':
                            await db._cache.remove_user_blacklist(row['id'])
                            if user and update:
                                await update_roles(user, session)
                        case 'server_blacklist':
                            await db._cache.remove_server_blacklist(row['id'])
                        case 'users':
                            await db._cache.remove_user(row['id'])
                        case 'auths':
                            await db._cache.remove_auth(row['id'])
                        case 'settings':
                            user = await db._cache.get_user(row['id'])
                            if user:
                                user._settings = {}
    except asyncio.CancelledError:
        stop.set()
        await session.close()