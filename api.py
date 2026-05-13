import orjson
import aiohttp
import os
import pymysql
import asyncio
import utils
import binlog
import shared
from datetime import datetime
from urllib.parse import quote, urlencode
from contextlib import asynccontextmanager
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import ORJSONResponse, Response
from slowapi import Limiter
from typing import Optional, List, TypedDict
from user import User, AuthData, Settings
from database import Database
from typing import Tuple, Union
from base64 import b64encode
from orjson import dumps
from starlette.responses import Response
from itsdangerous import URLSafeSerializer


class VerifyConfig(TypedDict):
    token: str
    id: int
    secret: str
    scope: List[str]


with open('config/verify.json', 'rb') as file:
    verify: VerifyConfig = orjson.loads(file.read())
with open('config/sql.json', 'rb') as file:
    sql_config = orjson.loads(file.read())
with open('config/config.json', 'rb') as file:
    config = orjson.loads(file.read())
with open('config/roles.json', 'rb') as file:
    role_config = orjson.loads(file.read())

api = APIRouter(prefix='/api')
db = Database()
session: aiohttp.ClientSession = None # type: ignore
signature = b64encode(dumps(verify)).decode()
serializer = URLSafeSerializer(signature, salt=b'grmn09')


class States:
    def __init__(self) -> None:
        self._states: list[tuple[str, datetime]] = []

    def add(self, state: str):
        if not state in self._states:
            self._states.append((state, utils.now(minutes=1)))

    def remove(self, state: str):
        for _state in self._states:
            if _state[0] == state: 
                self._states.remove(_state)
                break

    def check(self, state: str) -> bool:
        return state in [item[0] for item in self._states]
     
    async def cleanuploop(self):
        while True:
            for state in self._states[:]:
                if state[1] <= utils.now():
                    try:
                        self.remove(state[0])
                    except ValueError:
                        # Already removed by self.remove
                        pass
                await asyncio.sleep(0.1)
            await asyncio.sleep(1)


def get_ip(request: Request):
    if 'CF-Connecting-IP' in request.headers:
        return request.headers['CF-Connecting-IP']
    return request.client.host # pyright: ignore[reportOptionalMemberAccess]

if os.name == 'nt':
    HOST = 'http://localhost:2009'
else:
    HOST = 'https://fluc.lol'

redirect_uri = f'{HOST}/oauth-callback'
encoded_redirect_uri = quote(redirect_uri, safe='')
authorization = aiohttp.BasicAuth(str(verify['id']), verify['secret'])
limiter = Limiter(key_func=get_ip)
limit = limiter.limit
states = States()
headers = {
    'Authorization': f'Bot {config['manager']}',
    'Content-Type': 'application/json'
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global session
    session = aiohttp.ClientSession('https://discord.com/')
    loop = asyncio.get_running_loop()
    
    asyncio.create_task(states.cleanuploop())
    try:
        await db.connect(sql_config, config)
        await db._sync()
    except pymysql.OperationalError as exc:
        print(f'RUNNING IN OFFLINE MODE: {exc}')
    shared.db = db
    async with db and session:
        loop.create_task(binlog.run(loop, sql_config))
        # For debugging. uvicorn or fastapi blocking all output
        print(flush=True, end='')
        yield

async def test_user(request: Request) -> Union[Tuple[User, str], Tuple[None, None]]:
    user_id, access_token = await load_access(request)
    if user_id and access_token:
        user = await db.get_user(int(user_id))
        if user and user.auth:
            return user, access_token
    return None, None

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

async def update_roles(user: User, _session: Optional[aiohttp.ClientSession] = None) -> Optional[aiohttp.ClientResponse]:
    desired_roles = get_roles(user)
    if not desired_roles:
        return None
    if _session:
        __session = _session
    else:
        __session = session
    async with __session.get(f'/api/v10/guilds/{config['server_id']}/members/{user.id}', headers=headers) as response:
        if not response.ok:
            return None
        member_data = await response.json()
        current_roles = set(int(role) for role in member_data.get('roles', []))
    managed_roles = set(role_config.values())
    desired_roles = set(desired_roles)
    to_keep = current_roles - managed_roles
    to_add = desired_roles - set(role for role in current_roles if role not in managed_roles)
    all_roles = to_keep | to_add
    return await __session.patch(f'/api/v10/guilds/{config['server_id']}/members/{user.id}', json={'roles': list(all_roles)}, headers=headers)

async def add_user(user: User) -> Optional[aiohttp.ClientResponse]:
    if not user.auth:
        return
    data = {
        'access_token': user.auth.access_token,
        'roles': get_roles(user)
    }
    return await session.put(f'/api/v10/guilds/{config['server_id']}/members/{user.id}', json=data, headers=headers)

async def load_access(request: Request) -> Tuple[Optional[int], Optional[str]]:
    cookie = request.cookies.get('access')
    if cookie:
        try:
            decoded: str = serializer.loads(cookie)
        except Exception:
            return None, None
        user_id, access_token = decoded.split(':')
        return int(user_id), access_token
    return None, None

async def save_access(response: Response, user_id: int, access_token: str):
    response.set_cookie('access', serializer.dumps(f'{user_id}:{access_token}'), 60 * 60 * 24 * 360)

async def revoke(user: User) -> Optional[aiohttp.ClientResponse]:
    if not user.auth:
        return
    data = {
        'token': user.auth.access_token,
        'token_type_hint': 'access_token'
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    return await session.post('api/v10/oauth2/token/revoke', data=urlencode(data), headers=headers, auth=authorization)

async def refresh_token(auth: AuthData) -> Optional[Union[AuthData, int]]:
    async def update_user(token_type: str, access_token: str) -> Optional[int]:
        if auth.update_at > utils.now():
            return
        async with session.get('/api/users/@me', headers={
            'Authorization': f'{token_type} {access_token}'
        }) as response:
                if not response.ok:
                    return response.status
                user_data = await response.json()
        
        user = await db.get_user(user_data['id'])
        if not user:
            user = User.new(user_data['id'])
        user._data.update({
            'id': user_data['id'],
            # no email scope = verified 
            'verified': user_data.get('verified', True)
        })
        if user._auth:
            user._auth.update({
                'id': user_data['id'],
                'email': user_data.get('email'),
                'avatar': user_data['avatar'],
                'update_at': int(utils.now(minutes=10).timestamp())
            })
        await db.update_user(user)

    if auth.expires > utils.now():
        status = await update_user(auth.token_type, auth.access_token)
        if status:
            return status
        return auth

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': auth.refresh_token
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    async with session.post('/api/oauth2/token', data=urlencode(data), headers=headers, auth=authorization) as response:
        try:
            response.raise_for_status()
        except aiohttp.ClientResponseError:
            return None
        data = await response.json()
        auth._data.update(data)
        auth._data['expires'] = int(utils.now(seconds=data['expires_in']).timestamp())
        auth._data['update_at'] = int(utils.now(minutes=10).timestamp())
        await db.update_auth(auth)

    if auth:
        status = await update_user(auth.token_type, auth.access_token)
        if status:
            return status
    return auth

@api.get('/ping')
@limit('30/minute')
async def ping(request: Request):
    return ORJSONResponse({'msg': 'Pong'})

@api.delete('/account')
@limit('5/hour')
async def account_delete(request: Request):
    user_id, access_token = await load_access(request)
    if access_token and user_id:
        user = await db.get_user(user_id)
        if user:
            await revoke(user)
            user._data['is_premium'] = False
            user._data['is_super'] = False
            user._data['verified'] = False
            await update_roles(user)
            await db.delete_user(user.id)
        return ORJSONResponse({'msg': 'Account deleted'})
    return ORJSONResponse({'msg': 'Unauthorized'}, 401)

@api.get('/user')
@limit('10/second')
async def user(request: Request):
    user, access_token = await test_user(request)
    if not user or not user.auth:
        return ORJSONResponse({'msg': 'Unauthorized'}, 401)
    auth = user.auth
    if user.auth.access_token != access_token:
        return ORJSONResponse({'msg': 'Access token mismatch'}, 401)
    status = await refresh_token(auth)
    # Convert to string for JS compatibility
    user_id = str(user._data['id'])
    user._data['id'] = user_id # type: ignore
    if user._auth:
        user._auth['id'] = user_id # type: ignore
    user._data['auth'] = auth._data
    response = ORJSONResponse(user._data)
    if isinstance(status, AuthData):
        await save_access(response, status.id, status.access_token)
        response.set_cookie('fresh_login', '1', 3600)
    return response

@api.patch('/user')
@limit('5/minute')
async def patch_user(request: Request):
    user, access_token = await test_user(request)
    if not user:
        return ORJSONResponse({'msg': 'Unauthorized'}, 401)
    try:
        json = await request.json()
    except ValueError:
        return ORJSONResponse({'msg': 'Data must be provided in JSON format'}, 400)
    settings = json.get('settings')
    if settings:
        try:
            settings = Settings(settings)
        except Exception as exc:
            return ORJSONResponse({
                'error': f'{type(exc).__name__}',
                'msg': str(exc)
            })
        #  MORE CHECKS
        if not user.settings:
            await db.add_settings(user.id, settings)
        else:
            await db.update_settings(user.id, settings)
    return Response(status_code=200)