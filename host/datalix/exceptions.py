import aiohttp
from typing import Dict, Optional


class DatalixException(Exception):
    ...


class ClientException(DatalixException):
    ...


class EventRegistration(ClientException):
    ...


class HTTPException(DatalixException):
    message: Optional[str]
    reason: Optional[str]
    status: int
    response: aiohttp.ClientResponse

    def __init__(
        self,
        response: aiohttp.ClientResponse,
        json: Optional[Dict] = None,
        message: Optional[str] = None
    ) -> None:
        self.message = None
        if json and not message:
            self.message = json.get('message')
        
        if message and not self.message:
            self.message = message

        elif message:
            self.message = None

        self.reason = response.reason
        self.status = response.status
        self.response = response

        _message = f'{self.status} {self.reason}'
        if self.message:
            _message += f': {self.message}'
        super().__init__(_message)
        

class Unauthorized(HTTPException):
    ...


class Forbidden(HTTPException):
    ...


class RateLimited(HTTPException):
    retry_in: float

    def __init__(
        self,
        response: aiohttp.ClientResponse
    ) -> None:
        message = f'We are being rate limited. Try again later.'
        super().__init__(response, message=message)


class NotFound(HTTPException):
    ...