import asyncio
import utils
import aiohttp
import logging
from http import HTTPStatus
from uuid import uuid4
from urllib.parse import urlencode
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from slowapi.errors import RateLimitExceeded
from fastapi.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from typing import Optional
from itsdangerous import BadSignature
from user import User, AuthData
from api import (
    update_roles, add_user, load_access,
    save_access, config, verify, serializer,
    db, limiter, limit, HOST, authorization,
    redirect_uri, refresh_token, states
)
import api

app = FastAPI(lifespan=api.lifespan)
app.mount('/assets', StaticFiles(directory='./fluc.lol/dist/assets'))
app.mount('/public', StaticFiles(directory='./fluc.lol/src/assets'))
app.include_router(api.api)
app.add_middleware(SessionMiddleware, secret_key=api.signature)
app.state.limiter = limiter
    
def set_error(
    status: Optional[int] = None,
    error: Optional[str] = None,
    message: Optional[str] = None,
    response: Optional[RedirectResponse] = None
) -> RedirectResponse:
    if not response:
        response = RedirectResponse('/')
    if status:
        response.set_cookie('status', str(HTTPStatus(status).phrase))
    response.set_cookie('error', error or 'No info provided')
    if error and message:
        response.set_cookie('msg', message or 'No info provided')
    return response

def session() -> aiohttp.ClientSession:
    return api.session

@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    if exc.limit:
        retry_after = exc.limit.limit.get_expiry()
    else:
        retry_after = '-1'
    return JSONResponse({
        'msg': 'You are being rate limited. Please try again later.',
        'retry-in': retry_after
    }, 429)

@app.get('/join')
@limit('10/minute')
async def join(request: Request, profile: Optional[int] = None):
    return RedirectResponse('https://discord.gg/fluc')
    user_id, access = await load_access(request)
    if not profile:
        return RedirectResponse('/profile-selector?redirect=/join')
    if user_id and access:
        user = await db.get_user(user_id)
        if user and user.auth:
            if not user.id == profile:
                return RedirectResponse('/profile-selector?redirect=/join')
            auth = await refresh_token(user.auth)
            if isinstance(auth, AuthData):
                user._auth = auth._data
            response = await add_user(user)
            return RedirectResponse(f'https://discord.com/channels/{config['server_id']}/{config['lander']}')
    return RedirectResponse('/account/login?redirect=/join')

@app.get('/account/login')
@limit('5/minute')
async def account_login(request: Request, redirect: Optional[str] = None, force: Optional[bool] = None):
    user_id, access_token = await load_access(request)
    private_user_id = request.cookies.get('user_id')
    state = str(uuid4())
    states.add(state)
    if redirect:
        state += redirect
    url = f'https://discord.com/oauth2/authorize?client_id={verify['id']}&response_type=code&redirect_uri={redirect_uri}&scope={'+'.join(verify['scope'])}&state={state}'
    login_redirect = RedirectResponse(url)
    if private_user_id and not force:
        try:
            private_user_id = serializer.loads(private_user_id)
        except BadSignature:
            response = RedirectResponse(f'account/login?redirect={redirect}')
            response.delete_cookie('user_id')
            response.delete_cookie('access')
            response.delete_cookie('fresh_login')
            return response
    
        user = await db.get_user(private_user_id)
        if user and user.auth:
            response = RedirectResponse(redirect or '/')
            await save_access(response, user.id, user.auth.access_token)
            return response
        
    if user_id and access_token and not force:
        auth_data = await db._cache.get_auth(user_id)
        if auth_data and auth_data.access_token == access_token:
            return RedirectResponse(redirect or '/')
        login_redirect.delete_cookie('access')
        login_redirect.delete_cookie('fresh_login')
    return login_redirect

@app.get('/account/logout')
@limit('5/minute')
async def account_logout(request: Request):
    user_id, access_token = await load_access(request)
    if not user_id or not access_token:
        return set_error(401, 'Unauthorized')
    response = RedirectResponse('/')
    response.delete_cookie('access')
    response.delete_cookie('fresh_login')
    response.delete_cookie('user_id')
    return response

@app.get('/oauth-callback')
@limit('5/minute')
async def oauth_callback(
    request: Request,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    code: Optional[str] = None,
    state: Optional[str] = None
):
    if state and '/' in state:
        state, ref = state.split('/')
        ref = '/' + ref
    else:
        ref = None
    if not state or not states.check(state):
        redirect = '/account/login'
        if ref:
            redirect += f'?redirect={ref}'
        return RedirectResponse(redirect)

    states.remove(state)
    if error or not code:
        response = RedirectResponse('/')
        response.set_cookie('error', error or 'No code was returned.', 60)
        response.set_cookie('msg', error_description or 'No detail.', 60)
        return response
    
    async with session().post('/api/oauth2/token', data=urlencode({
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': f'{HOST}/oauth-callback'
    }), headers={
        'Content-Type': 'application/x-www-form-urlencoded'
    }, auth=authorization) as response:
        token_data = await response.json()
        if not response.ok:
            if isinstance(token_data, dict):
                return set_error(
                    response.status,
                    token_data.get('error'),
                    token_data.get('error_description')
                )
            return set_error(
                response.status,
                'Unknow error occured',
                await response.text()
            )

    async with session().get('/api/users/@me', headers={
        'Authorization': f'{token_data['token_type']} {token_data['access_token']}'
    }) as response:
        if not response.ok:
            return set_error(
                response.status,
                token_data.get('error'),
                token_data.get('error_description')
            )
        user_data = await response.json()
    
    auth_data = AuthData({
        'id': user_data['id'],
        'username': user_data['username'],
        'avatar': user_data['avatar'],
        # 'email': user_data.get('email'),
        'access_token': token_data['access_token'],
        'token_type': token_data['token_type'],
        'scope': token_data['scope'],
        'refresh_token': token_data['refresh_token'],
        'expires': int(utils.now(seconds=token_data['expires_in']).timestamp()),
        'update_at': int(utils.now(minutes=10).timestamp())
    })
    user = await db.get_user(auth_data.id)
    if not user:
        user = User.new(auth_data.id)
        await db.add_user(user)
    # user._data['verified'] = user_data['verified']
    user._data['verified'] = True
    user._auth = auth_data._data
    await db.update_user(user)
    response = RedirectResponse(ref or '/')
    await save_access(response, auth_data.id, auth_data.access_token)
    response.set_cookie('user_id', serializer.dumps(str(auth_data.id)), 60 * 60 * 24 * 360)
    response.set_cookie('fresh_login', expires=auth_data.expires)
    return response

@app.get('/authorize')
@limit('5/minute')
async def authorize(
    request: Request,
    profile: Optional[int] = None
):
    user_id, access = await load_access(request)
    if not profile or not profile == user_id:
        return RedirectResponse('/profile-selector?redirect=/authorize')
    if None in (user_id, access):
        return RedirectResponse('/account/login?redirect=/authorize')
    # Pylance slow
    assert user_id
    user = await db.get_user(user_id)
    if not user or not user.auth:
        # Should be unreachable
        return RedirectResponse('/account/login?redirect=/authorize')
    status = await refresh_token(user.auth)
    if status == 401:
        return RedirectResponse('/account/login?redirect=/authorize')
    # Manual update in database
    await db.get_premium(user.id)
    await db.get_user_blacklist(user.id)
    await db.get_super(user.id)
    asyncio.create_task(update_roles(user))
    html = '<p>Process completed. If this page doesn\'t close automatically, you can close it now.</p><script>window.onload = () => {window.close();}</script>'
    response = HTMLResponse(html)
    await save_access(response, user.auth.id, user.auth.access_token)
    return response

@app.get('/{full_path:path}')
@limit('10/second')
async def frontend(full_path: str, request: Request):
    if full_path.startswith('api'):
        raise HTTPException(404)
    return FileResponse('./fluc.lol/dist/index.html')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('backend:app', host='127.0.0.1', port=2009, log_level=logging.DEBUG)