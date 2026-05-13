import asyncio
from orjson import loads
from database import Database, Profile

with open('config/sql.json', 'rb') as file:
    config = loads(file.read())

async def main() -> None:
    db = Database()
    await db.connect(mysql=config)
    async with db:
        data = {
            'id': input('ID: ...'),
            'username': input('Username: ...'),
            'token': input('Token: ...')
        }
        profile = Profile(data)
        await db.add_profile(profile)
        print('Success')    

asyncio.run(main())