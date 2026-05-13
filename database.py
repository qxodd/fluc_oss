import orjson
import aiomysql
import logging
import asyncio
import warnings
import utils
import uuid
import traceback
from backup import BackupData
from pymysql.err import OperationalError, IntegrityError
from collections import defaultdict
from datetime import datetime, UTC
from user import User, AuthData, Settings, TUser
from typing import List, Any, Literal, overload, Dict, Tuple, Optional, Union

log = logging.getLogger(__name__)
warnings.filterwarnings('ignore')


class Profile:
    _data: Dict[str, Any]
    id: int
    username: str
    token: str

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.id = data['id']
        self.username = data['username']
        self.token = data['token']


class Cache:
    owner_id: int
    supers: List[int]
    profiles: List[Profile]
    user_blacklist: List[int]
    server_blacklist: List[int]
    premium: List[int]
    users: List[User]
    auths: List[AuthData]
    stats: Dict[str, int]

    def __init__(self) -> None:
        self.supers = []
        self.profiles = []
        self.user_blacklist = []
        self.server_blacklist = []
        self.premium = []
        self.users = []
        self.auths = []
        self.stats = {}
        self.expiration_table: Dict[int, Dict[int, Optional[datetime]]] = defaultdict(dict)

    async def add_super(self, user_id: int, expires_at: Optional[datetime]) -> bool:
        traceback.print_stack()
            
        if not user_id in self.supers:
            self.supers.append(user_id)
            self.expiration_table[0][user_id] = expires_at
            user = await self.get_user(user_id)
            if user:
                user._data['is_super'] = True
            return True
        return False
    
    async def get_super(self, user_id: int) -> Optional[User]:
        if user_id in self.supers:
            return await self.get_user(user_id)
    
    async def remove_super(self, user_id: int) -> bool:
        if user_id in self.supers:
            self.supers.remove(user_id)
            self.expiration_table[0].pop(user_id)
            user = await self.get_user(user_id)
            if user:
                user._data['is_super'] = False
            return True
        return False
    
    async def add_profile(self, profile: Profile) -> bool:
        if not profile in self.profiles:
            self.profiles.append(profile)
            return True
        return False
    
    async def get_profile(self, profile_id: int) -> Optional[Profile]:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
            
    async def update_profile(self, profile: Profile) -> bool:
        old_profile = await self.get_profile(profile.id)
        if old_profile:
            old_profile._data = profile._data
            return True
        return False
    
    async def remove_profile(self, profile_id: int) -> bool:
        for profile in self.profiles[:]:
            if profile.id == profile_id:
                self.profiles.remove(profile)
                return True
        return False
    
    async def add_user(self, user: User) -> bool:
        if not user in self.users:
            self.users.append(user)
            self.expiration_table[4][user.id] = utils.now(minutes=5)
            return True
        return False
    
    async def get_user(self, user_id: int) -> Optional[User]:
        for user in self.users:
            if user.id == user_id:
                return user
            
    async def remove_user(self, user_id: int) -> bool:
        await self.remove_auth(user_id)
        for user in self.users[:]:
            if user.id == user_id:
                self.users.remove(user)
                return True
        return False
            
    async def add_auth(self, auth: AuthData) -> bool:
        if not auth in self.auths:
            self.auths.append(auth)
            return True
        return False
    
    async def get_auth(self, user_id: int) -> Optional[AuthData]:
        for auth in self.auths:
            if auth.id == user_id:
                return auth
            
    async def update_auth(self, auth: AuthData) -> bool:
        data = auth._data
        old_auth = await self.get_auth(auth.id)
        if old_auth and data == old_auth._data:
            return True
        for user in self.users:
            if user.id == auth.id:
                if user._auth:
                    user._auth.update(data)
                    break
        if old_auth:
            old_auth._data = data
            return True
        return False

    async def remove_auth(self, user_id: int) -> bool:
        for auth in self.auths[:]:
            if auth.id == user_id:
                self.auths.remove(auth)
                return True
        return False

    async def add_user_blacklist(self, user_id: int, expires_at: Optional[datetime]) -> bool:
        if not user_id in self.user_blacklist:
            user = await self.get_user(user_id)
            if user:
                user._data['is_blacklisted'] = True
            self.user_blacklist.append(user_id)
            self.expiration_table[1][user_id] = expires_at
            return True
        return False
    
    async def remove_user_blacklist(self, user_id: int) -> bool:
        if user_id in self.user_blacklist:
            user = await self.get_user(user_id)
            if user:
                user._data['is_blacklisted'] = False
            self.user_blacklist.remove(user_id)
            self.expiration_table[1].pop(user_id)
            return True
        return False
    
    async def add_server_blacklist(self, server_id: int, expires_at: Optional[datetime]) -> bool:
        if not server_id in self.server_blacklist:
            self.server_blacklist.append(server_id)
            self.expiration_table[2][server_id] = expires_at
            return True
        return False
    
    async def update_server_blacklist(self, server_id: int, expires_at: Optional[datetime]) -> bool:
        try:
            await self.remove_server_blacklist(server_id)
        finally:
            await self.add_server_blacklist(server_id, expires_at)
        return True
    
    async def remove_server_blacklist(self, server_id: int) -> bool:
        if server_id in self.server_blacklist:
            self.server_blacklist.remove(server_id)
            self.expiration_table[2].pop(server_id)
            return True
        return False
    
    async def add_premium(self, user_id: int, expires_at: Optional[datetime]) -> bool:
        if not user_id in self.premium:
            self.premium.append(user_id)
            user = await self.get_user(user_id)
            if user:
                user._data['is_premium'] = True
            self.expiration_table[3][user_id] = expires_at
            return True
        return False
    
    async def remove_premium(self, user_id: int) -> bool:
        if user_id in self.premium:
            self.premium.remove(user_id)
            user = await self.get_user(user_id)
            if user:
                user._data['is_premium'] = False
            self.expiration_table[3].pop(user_id)
            return True
        return False
    
    async def set_stats(self, server_amount: int, user_amount: int) -> Literal[True]:
        self.stats.update({
            'server_amount': server_amount,
            'user_amount': user_amount
        })
        return True
    
    async def expiration_loop(self):
        while True:
            now = utils.now()
            for item in list(self.expiration_table.values()):
                for key, value in item.items():
                    if value and now >= value:
                        match key:
                            case 0:
                                await self.remove_super(key)
                            case 1:
                                await self.remove_user_blacklist(key)
                            case 2:
                                await self.remove_server_blacklist(key)
                            case 3:
                                await self.remove_premium(key)
                            case 4:
                                await self.remove_user(key)
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.5)


class Database:
    _cache: Cache
    closed: bool
    pool: aiomysql.Pool

    def __init__(self) -> None:
        self.closed = True
        self._cache = Cache()
        self.pool = None # type: ignore

    @property
    def owner_id(self) -> int:
        return self._cache.owner_id

    async def _check(self) -> None:
        log.debug('Updating tables.')
        async def create(table: str) -> None:
            await self.query(f'CREATE TABLE IF NOT EXISTS {table}')
        await create('profiles(id BIGINT PRIMARY KEY, username TEXT, token TEXT)')
        await create('user_blacklist(id BIGINT PRIMARY KEY, expires BIGINT NOT NULL DEFAULT 0)')
        await create('server_blacklist(id BIGINT PRIMARY KEY, expires BIGINT NOT NULL DEFAULT 0)')
        await create('premium(id BIGINT PRIMARY KEY, expires BIGINT NOT NULL DEFAULT 0)')
        await create('supers(id BIGINT PRIMARY KEY, expires BIGINT NOT NULL DEFAULT 0)')
        await create('stats(server_amount INTEGER, user_amount INTEGER)')
        await create('auths(id BIGINT PRIMARY KEY, username TEXT, avatar TEXT, access_token TEXT, token_type TEXT, expires BIGINT, refresh_token TEXT, scope TEXT, email TEXT, last_updated BIGINT)')
        await create('settings(id BIGINT PRIMARY KEY, data JSON)')
        await create('users(id BIGINT PRIMARY KEY, server_amount INTEGER, user_amount INTEGER, verified BOOLEAN)')
        await create('backups(id BIGINT PRIMARY KEY, user_id BIGINT, server_id BIGINT, server_name TEXT, unlock_key TEXT, data BLOB, expires_at BIGINT NOT NULL DEFAULT 0)')
        await create('tokens(token VARCHAR(255) NOT NULL, user_id BIGINT NOT NULL)')

    async def wipe(self) -> None:
        tables = [
            'profiles',
            'user_blacklist',
            'server_blacklist',
            'premium',
            'supers',
            'auths',
            'settings',
            'users',
            'backup'
        ]
        for table in tables:
            await self.query(f'TRUNCATE TABLE {table};')

    async def _sync(self) -> None:
        log.debug('Syncing and writing to cache...')
        async def select(table: str, target: str, condition: str = '', *args) -> Any:
            return await self.query(f'SELECT {target} FROM {table} {condition}', *args, fetch_all=True)
        
        rows = await select('profiles', '*')
        for row in rows:
            profile = Profile(row)
            await self._cache.add_profile(profile)

        rows = await select('user_blacklist', '*')
        for row in rows:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_user_blacklist(row['id'], expires)
        
        rows = await select('server_blacklist', '*')
        for row in rows:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_server_blacklist(row['id'], expires)

        rows = await select('supers', '*')
        for row in rows:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_super(row['id'], expires)

        rows = await select('premium', '*')
        for row in rows:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_premium(row['id'], expires)

        rows = await select('users', '*')
        for row in rows:
            is_super = row['id'] in self._cache.supers
            is_owner = row['id'] == self._cache.owner_id
            is_premium = row['id'] in self._cache.premium
            if is_super or is_owner or is_premium:
                row.update({
                    'is_owner': is_owner,
                    'is_super': is_super,
                    'is_elevated': is_owner or is_super,
                    'is_premium': is_premium,
                    'is_blacklisted': row['id'] in self._cache.user_blacklist,
                    'server_amount': row['server_amount'],
                    'user_amount': row['user_amount']
                })
                data = await select('settings', 'data', 'WHERE id=%s', row['id'])
                auth = await select('auths', '*', 'WHERE id=%s', row['id'])
                if data:
                    row['settings'] = orjson.loads(data[0]['data'])
                if auth:
                    row['auth'] = AuthData(auth[0])
                user = User(row)
                await self._cache.add_user(user)
        await self.get_stats()
        asyncio.create_task(self._cache.expiration_loop())
        
    async def connect(self, mysql: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> None:
        log.debug(f'Connecting to {mysql['database']}.')
        self.connect_settings = [mysql, config]
        pool = await aiomysql.create_pool(
            host=mysql['host'],
            user=mysql['user'],
            password=mysql.get('password'),
            db=mysql['database'],
            port=mysql.get('port') or 3306,
            pool_recycle=3600,
            autocommit=True
        )
        self.pool = pool
        if config:
            self._cache.owner_id = config['owner_id']
        self.closed = False

    async def add_profile(self, profile: Profile) -> bool:
        if await self.get_profile(profile.id):
            return False
        await self.query(
            'INSERT INTO profiles(id, username, token) VALUES(%s, %s, %s)',
            (profile.id, profile.username, profile.token)
        )
        await self._cache.add_profile(profile)
        return True

    async def get_profile(self, profile_id: Optional[int] = None) -> Optional[Profile]:
        if profile_id:
            profile = await self._cache.get_profile(profile_id)
            if profile:
                return profile
        rows = await self.query('SELECT * FROM profiles', fetch_all=bool(profile_id))
        if not rows or not len(rows):
            return
        if profile_id and isinstance(rows, list):
            for row in rows: # pyright: ignore[reportAssignmentType]
                row: Dict[str, List[Any]]
                if row['id'] == profile_id:
                    return Profile(row)
        if not profile_id and isinstance(rows, dict):
            return utils.optional(Profile, rows)
    
    async def remove_profile(self, profile_id: int) -> bool:
        profile =  await self.get_profile(profile_id)
        if not profile:
            return False
        await self.query('DELETE FROM profiles WHERE id=%s', (profile.id,))
        await self._cache.remove_profile(profile.id)
        return True

    async def add_user(self, user: User) -> bool:
        if await self._cache.get_user(user.id):
            return False
        await self.query(
            'INSERT INTO users(id, server_amount, user_amount, verified) VALUES(%s, %s, %s, %s)',
            (user.id, user.server_amount, user.user_amount, user.verified)
        )
        if user.auth:
            await self.add_auth(user.auth)
        if user.is_premium:
            await self.add_premium(user.id, None)
        if user.is_blacklisted:
            await self.add_user_blacklist(user.id)
        await self._cache.add_user(user)
        await self.get_super(user.id)
        await self.get_auth(user.id)
        await self.get_settings(user.id)
        return True
    
    async def update_user(self, user: User) -> bool:
        old_user = await self.get_user(user.id)
        if not old_user:
            return False
        await self.query(
            'UPDATE users SET id=%s, server_amount=%s, user_amount=%s, verified=%s WHERE id=%s',
            (user.id, user.server_amount, user.user_amount, user.verified, user.id)
        )
        old_user._data = user._data
        if not old_user.is_super and user.is_super:
            await self.add_super(user.id)
        elif old_user.is_super and not user.is_super:
            await self.delete_super(user.id)
        if not old_user.is_blacklisted and user.is_blacklisted:
            await self.add_user_blacklist(user.id)
        elif old_user.is_blacklisted and not user.is_blacklisted:
            await self.delete_user_blacklist(user.id)
        if not old_user.is_premium and user.is_premium:
            await self.add_premium(user.is_premium, None)
        elif old_user.is_premium and not user.is_premium:
            await self.delete_premium(user.is_premium)
            
        if user.auth and not old_user.auth:
            await self.add_auth(user.auth)
        elif not user.auth and old_user.auth:
            await self.delete_auth(user.id)
        elif user.auth and old_user.auth:
            await self.update_auth(user.auth)
        if user.settings._data and not old_user.settings._data:
            await self.add_settings(user.id, user.settings)
        elif not user.settings and old_user.settings:
            await self.delete_settings(user.id)
        elif not user.settings._data == old_user.settings._data:
            await self.update_settings(user.id, user.settings)
        return True
    
    async def get_user(self, user_id: int) -> Optional[User]:
        user = await self._cache.get_user(user_id)
        if user:
            return user
        if not user:
            row = await self.query('SELECT * FROM users WHERE id=%s', (user_id,))
            if row:
                settings = await self.get_settings(user_id)
                auth = await self.get_auth(user_id, no_update=True)
                is_super = bool(await self.get_super(user_id))
                owner_id = getattr(self._cache, 'owner_id', None)
                is_owner = user_id == owner_id
                data: TUser = {
                    'id': user_id,
                    'is_owner': is_owner,
                    'is_super': is_super,
                    'is_premium': await self.get_premium(user_id),
                    'is_elevated': is_owner or is_super, 
                    'is_blacklisted': await self.get_user_blacklist(user_id),
                    'server_amount': row['server_amount'] or 0,
                    'user_amount': row['user_amount'] or 0,
                    'verified': row['verified'],
                    'settings': settings._data if settings else None,
                    'auth': auth._data if auth else None
                }
                user = User(data)
                await self._cache.add_user(user)
            else:
                user = None
        return user
    
    async def delete_user(self, user_id: int) -> bool:
        user = await self._cache.get_user(user_id)
        if not user:
            user = await self.get_user(user_id)
        if not user:
            return False
        await self.delete_auth(user.id)
        await self.delete_settings(user.id)
        await self.delete_premium(user.id)
        await self.delete_super(user.id)
        await self.query('DELETE FROM users WHERE id=%s', (user_id,))
        await self._cache.remove_user(user.id)
        return True
    
    async def add_super(self, user_id: int) -> bool:
        if user_id in self._cache.supers:
            return False
        expires = utils.now(days=30)
        await self.query('INSERT INTO supers(id, expires) VALUES(%s, %s)', (user_id, expires.timestamp()))
        await self._cache.add_super(user_id, expires)
        return True
    
    async def get_super(self, user_id: int) -> Optional[User]:
        user = await self._cache.get_super(user_id)
        if user:
            return user
        row = await self.query('SELECT * FROM supers WHERE id=%s', (user_id,))
        if row:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_super(user_id, expires)
            return await self._cache.get_super(user_id)

    async def delete_super(self, user_id: int) -> bool:
        if user_id not in self._cache.supers:
            return False
        await self.query('DELETE FROM supers WHERE id=%s', (user_id,))
        await self._cache.remove_super(user_id)
        return True
    
    async def add_user_blacklist(self, user_id: int, expires: Optional[datetime] = None) -> bool:
        if user_id in self._cache.user_blacklist:
            return False
        expires = expires or utils.now(days=31)
        expires_ts = int(expires.timestamp())
        await self.query('INSERT INTO user_blacklist(id, expires) VALUES(%s, %s)', (user_id, expires_ts))
        await self._cache.add_user_blacklist(user_id, expires)
        return True
    
    async def get_user_blacklist(self, user_id: int) -> bool:
        return user_id in self._cache.user_blacklist
        row = await self.query('SELECT * FROM user_blacklist WHERE id=%s', (user_id,))
        if row:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.add_user_blacklist(row['id'], expires)
            return True
        return False

    async def delete_user_blacklist(self, user_id: int) -> bool:
        if not user_id in self._cache.user_blacklist:
            return False
        await self.query('DELETE FROM user_blacklist WHERE id=%s', (user_id,))
        await self._cache.remove_user_blacklist(user_id)
        return True
    
    async def add_server_blacklist(self, server_id: int, expires: Optional[datetime] = None) -> bool:
        if server_id in self._cache.server_blacklist:
            return False
        expires = expires or utils.now(days=360)
        expires_ts = int(expires.timestamp())
        await self.query('INSERT INTO server_blacklist(id, expires) VALUES(%s, %s)', (server_id, expires_ts))
        await self._cache.add_server_blacklist(server_id, expires)
        return True
    
    async def get_server_blacklist(self, server_id: int) -> bool:
        return server_id in self._cache.server_blacklist
        row = await self.query('SELECT * FROM server_blacklist WHERE id=%s', (server_id,))
        if row:
            expires = utils.optional(datetime.fromtimestamp, row['expires'], UTC)
            await self._cache.update_server_blacklist(row['id'], expires)
            return True
        return False
    
    async def delete_server_blacklist(self, server_id: int) -> bool:
        if not server_id in self._cache.server_blacklist:
            return False
        await self.query('DELETE FROM server_blacklist WHERE id=%s', (server_id,))
        await self._cache.remove_server_blacklist(server_id)
        return True
        
    async def add_auth(self, auth: AuthData) -> bool:
        old_auth = await self._cache.get_auth(auth.id)
        if old_auth:
            return False
        await self.query(
            'INSERT INTO auths(id, username, avatar, access_token, token_type, expires, refresh_token, scope, email, update_at) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (auth.id, auth.username, auth.avatar, auth.access_token, auth.token_type, int(auth.expires.timestamp()), auth.refresh_token, auth.scope, auth.email, auth.update_at.timestamp())
        )
        await self._cache.add_auth(auth)
        return True
    
    async def update_auth(self, auth: AuthData) -> bool:
        old_auth = await self.get_auth(auth.id)
        if not old_auth:
            return await self.add_auth(auth)
        if old_auth._data == auth._data:
            return True
        await self.query(
            'UPDATE auths SET id=%s, username=%s, avatar=%s, access_token=%s, token_type=%s, expires=%s, refresh_token=%s, scope=%s, email=%s, update_at=%s WHERE id=%s',
            (auth.id, auth.username, auth.avatar, auth.access_token, auth.token_type, auth.expires.timestamp(), auth.refresh_token, auth.scope, auth.email, auth.update_at.timestamp(), auth.id)
        )
        await self._cache.update_auth(auth)
        return True
 
    async def get_auth(self, user_id: int, *, raw: bool = False, no_update: bool = False) -> Optional[AuthData]:
        auth = await self._cache.get_auth(user_id)
        if auth:
            return auth
        row: Optional[TAuthData] = await self.query('SELECT * FROM auths WHERE id=%s', (user_id,)) # type: ignore
        auth = utils.optional(AuthData, row)
        if auth:
            await self._cache.update_auth(auth)
        return auth
    
    async def delete_auth(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user or not user.auth:
            return False
        await self.query('DELETE FROM auths WHERE id=%s', (user_id,))
        await self._cache.remove_auth(user_id)
        user._auth = None
        return True
    
    async def add_premium(self, user_id: int, expires: Optional[datetime] = None) -> bool:
        user = await self.get_user(user_id)
        if not user or user.is_premium:
            return False
        await self.query('INSERT INTO premium(id, expires) VALUES(%s, %s)', (user.id, int(expires.timestamp() if expires else 0)))
        await self._cache.add_premium(user_id, expires)
        return True
    
    async def get_premium(self, user_id: int) -> bool:
        return user_id in self._cache.premium
        row = await self.query('SELECT * FROM premium WHERE id=%s', (user_id,))
        if row:
            expires = datetime.fromtimestamp(row['expires'], UTC)
            await self._cache.add_premium(user_id, expires)
            return True
        await self._cache.remove_premium(user_id)
        return False

    async def delete_premium(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user or not user.is_premium:
            return False
        await self.query('DELETE FROM premium WHERE id=%s', (user_id,))
        await self._cache.remove_premium(user_id)
        return True
    
    @overload
    async def get_backup(self, backup_id: Optional[str] = None) -> Optional[Tuple[str, BackupData]]:
        ...

    @overload
    async def get_backup(self, user_id: Optional[int] = None) -> List[Dict[str, Tuple[str, BackupData]]]:
        ...

    async def get_backup( # pyright: ignore[reportInconsistentOverload]
        self,
        backup_id: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Union[Optional[Dict[str, BackupData]], List[Dict[str, BackupData]]]:
        if backup_id:
            backups = await self.query(
                'SELECT * FROM backups WHERE id=%s',
                (backup_id,),
                fetch_all=True
            )
        elif user_id:
            backups = await self.query(
                'SELECT * FROM backups WHERE id=%s',
                (user_id,),
                fetch_all=True
            )
        else:
            return None

        if backup_id:
            for backup in backups:
                if backup['id'] == backup_id:
                    return backup['key'], backup['data'] # pyright: ignore[reportReturnType]
        elif user_id:
            _backups = {}
            for backup in backups:
                _backups[backup['id']] = (backup['key'], backup['data'])
            return _backups
        
    async def add_backup(self, user_id: int, backup: BackupData) -> Optional[str]:
        backup_id = uuid.uuid4()
        
    async def add_settings(self, user_id: int, settings: Settings) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        blob = orjson.dumps(settings._data)
        await self.query(
            'INSERT INTO settings(id, data) VALUES(%s, %s)',
            (user_id, blob)
        )
        user._settings = settings._data
        return True
                
    @overload
    async def get_settings(self, user_id: int, *, raw: Literal[False] = ...) -> Optional[Settings]:
        ...
    
    @overload
    async def get_settings(self, user_id: int, *, raw: Literal[True] = ...) -> Optional[Dict[str, Any]]:
        ...
    
    async def get_settings(self, user_id: int, *, raw: bool = False) -> Union[Optional[Settings], Optional[Dict[str, Any]]]:
        user = await self._cache.get_user(user_id)
        if user and 0:
            return user.settings
        row = await self.query('SELECT data FROM settings WHERE id=%s', (user_id,))
        if row and row.get('data'):
            # row is bytes
            decoded = orjson.loads(row['data']) # pyright: ignore[reportArgumentType]
            if user:
                user._settings = decoded
            if raw or not decoded:
                return decoded or None
            s = Settings(decoded)
            return s
    
    async def update_settings(self, user_id: int, settings: Settings) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        old_settings = user.settings
        if not settings._data:
            return await self.delete_settings(user_id)
        if not old_settings._data:
            return await self.add_settings(user_id, settings)
        blob = orjson.dumps(settings._data)
        await self.query('UPDATE settings SET data=%s WHERE id=%s', (blob, user_id))
        if not await self.get_settings(user_id) and settings._data: 
            await self.add_settings(user_id, settings)
        user._settings = settings._data
        return True
    
    async def delete_settings(self, user_id: int) -> bool:
        user = await self._cache.get_user(user_id)
        if not user or not user.settings:
            return False
        await self.query('DELETE FROM settings WHERE id=%s', (user_id,))
        user._settings = {}
        return True
    
    async def add_token(self, user_id: int, token: str) -> bool:
        try:
            await self.query('INSERT INTO tokens(token, user_id) values(%s, %s)', (token, user_id))
        except IntegrityError:
            return False
        return True
    
    async def get_tokens(self, user_id: int) -> list[str]:
        rows = await self.query('SELECT token FROM tokens where user_id=%s', (user_id,), fetch_all=True)
        return [row['token'] for row in rows]

    async def delete_token(self, user_id: int, token: str) -> bool:
        try:
            await self.query('DELETE FROM tokens WHERE token=%s AND user_id=%s', (token, user_id))
        except OperationalError:
            return False
        return True
    
    async def get_stats(self) -> Dict[str, int]:
        if self._cache.stats:
            return self._cache.stats
        stats = await self.query('SELECT * FROM stats')
        if stats:
            await self._cache.set_stats(stats['server_amount'], stats['user_amount'])
        else:
            await self.query('INSERT INTO stats(server_amount, user_amount) VALUES(%s, %s)', (0, 0))
            await self._cache.set_stats(0, 0)
        return self._cache.stats
    
    @overload
    async def query(self, sql: str, params: Tuple[Any, ...] = ..., *, row_count: Literal[False] = ..., fetch_all: Literal[False] = ...) -> Optional[Dict[str, Any]]:
        ...

    @overload
    async def query(self, sql: str, params: Tuple[Any, ...] = ..., *, row_count: Literal[False] = ..., fetch_all: Literal[True]) -> Tuple[Dict[str, Any]]:
        ...

    @overload
    async def query(self, sql: str, params: Tuple[Any, ...] = ..., *, row_count: Literal[True]) -> int:
        ...

    async def query(self, sql: str, params: Tuple[Any, ...] = (), *, row_count: bool = False, fetch_all: bool = False) -> Union[int, Tuple[Dict[str, List[Any]]], Optional[Dict[str, Any]]]:
        while 1:
            if not self.pool:
                log.error(f'Connection is closed. Could not execute: {sql}, {params}')
                log.info('Reconnecting to Database...')
                await self.connect(*self.connect_settings)
                await self._sync()
                continue
            break
        
        async with self.pool.acquire() as conn:
            conn: aiomysql.Connection
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                cursor: aiomysql.Cursor
                try:
                    await cursor.execute(sql, params)
                    log.debug(f'Executed: {sql} {params}')
                except OperationalError as exc:
                    log.critical(f'Error while quering {sql} {params}: {exc}')
                    # await self.close()
                if row_count:
                    return cursor.rowcount
                if fetch_all:    
                    return await cursor.fetchall()
                return await cursor.fetchone()
            
    async def __aenter__(self, *args) -> None:
        await self._check()
        if not getattr(self._cache, 'owner_id', None):
            # Partial DB
            return
        await self._sync()

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def close(self) -> None:
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
        self.closed = True
