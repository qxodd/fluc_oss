import aiohttp
from http import HTTPStatus
from asyncio import sleep
from logging import getLogger
from yarl import URL
from typing import Literal, Union, Dict
from .exceptions import *

_log = getLogger(__name__)


class Request:
    method: str
    url: URL
    options: Dict

    def __init__(
        self,
        method: Literal[
            'GET',
            'POST',
            'DELETE',
            'PUT'
        ],
        path: Union[
            URL,
            str
        ],
        *,
        api: bool = True,
        **options
    ):
        self.method = method
        self.options = options

        if api:
            path = f'https://backend.datalix.de/v1{path}'

        if isinstance(path, URL):
            self.url = path
        elif isinstance(path, str):
            self.url = URL(path)

    def authorize(self, token: str):
        if not 'token' in self.url.query:
            self.url = self.url.update_query(token=token)


class HTTP:
    session: aiohttp.ClientSession
    token: str

    def __init__(self, token: str) -> None:
        self.session = aiohttp.ClientSession()
        self.token = token
        self.max_tries = 3
    
    async def request(
        self,
        request: Request
    ) -> aiohttp.ClientResponse:
        request.authorize(self.token)

        for i in range(self.max_tries):
            response = await self.session.request(
                request.method,
                request.url,
                **request.options
            )
            log_msg = f'{response.url} responded with {response.status} {response.reason}'
            json = {}
            if not response.ok:
                try:
                    json = await response.json()
                except Exception:
                    pass

            if response.status in range(200, 400):
                _log.debug(log_msg)
                return response
            
            elif response.status in range(400, 500):
                _log.error(log_msg)

                handled_errors = [status.value for status in (
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                    HTTPStatus.TOO_MANY_REQUESTS,
                    HTTPStatus.NOT_FOUND
                )]

                if not response.status in handled_errors:
                    response.raise_for_status()

                if response.status == handled_errors[0]:
                    raise Unauthorized(response, json)

                elif response.status == handled_errors[1]:
                    raise Forbidden(response, json)
                
                elif response.status == handled_errors[2]:
                    raise RateLimited(response)
                
                elif response.status == handled_errors[3]:
                    raise NotFound(response, json)
                raise HTTPException(response, json)
                
            elif response.status in range(500, 600):
                await sleep(1 + self.max_tries * 3)
                if self.max_tries == i - 1:
                    raise HTTPException(response, json, message='5xx response')
                continue
        raise NotImplemented