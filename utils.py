from __future__ import annotations

import ffmpeg
import discord
from discord.ext import commands
from discord.types.embed import Embed as TEmbed
from random import random
from emoji import EMOJI_DATA
from string import ascii_letters, digits
from dataclasses import field
from PIL import Image
from datetime import datetime, UTC, timedelta
from io import BytesIO
from orjson import loads, dumps
from typing import (
    Tuple, Dict, Any, List, overload, Literal, Union, Optional,
    get_args, get_origin, Sequence, Callable, Iterator, TYPE_CHECKING
)

if TYPE_CHECKING:
    from shared import Cooldowns


class Xorshift32:
    state: int
    seed: int

    def __init__(self, seed: int = int(random() * 10 ** 15)) -> None:
        self.seed = seed
        self.state = self.seed
        self.magic = 0xFFFFFFFF

    def next(self) -> float:
        '''
        Returns pseudo-random value

        Result will be stored in :attr:`state`

        Returns
        -------
        float
            Pseudo-random value generated 
        '''
        self.state ^= (self.state << 13) & self.magic
        self.state ^= (self.state >> 17) & self.magic
        self.state ^= (self.state << 5) & self.magic
        return self.state
    
    @overload
    def choice[T](self, seq: Sequence[T], *, length: None = ...) -> T:
        ...
    
    @overload
    def choice[T](self, seq: Sequence[T], *, length: int) -> List[T]:
        ...
    
    def choice[T](self, seq: Sequence[T], *, length: Optional[int] = None) -> Union[T, List[T]]:
        '''
        Chooses pseudo-random item from given sequence

        Parameters
        ----------
        seq : Sequence[T]
            Sequence to use
        length : Optional[int]
            Amount of items to choose, default 1

        Returns
        -------
        T
            Pseudo-random item from `seq`
        '''
        def next_index() -> int:
            self.next()
            return self.state % len(seq)

        if length:
            indexes = []
            for _ in range(length):
                indexes.append(next_index())
            return [seq[index] for index in indexes]
        return seq[next_index()]
    

xs32 = Xorshift32()


def to_ascii(text: str) -> str:
    '''
    Strips all non ASCII characters from given text

    Parameters
    ----------
    text : str
        The text to use

    Returns
    -------
    str
        Text in ASCII format
    '''
    return ''.join([char for char in text if char in digits + ascii_letters])

def underscore(item: Dict[Any, str | Any]) -> Dict[Any, str | Any]:
    '''
    Adds a underscore to lal

    _extended_summary_

    Parameters
    ----------
    item : Dict[Any, str  |  Any]
        _description_

    Returns
    -------
    Dict[Any, str | Any]
        _description_
    '''
    ret = {}
    for key, value in item.copy().items():
        if isinstance(key, str):
            ret['_' + key] = value
        else:
            ret[key] = value
    return ret

def default_field(item: Any) -> Any:
    return field(default_factory=lambda: item)

def trim(video: bytes, start: int = 0, duration: int = 5) -> bytes:
    buffer = BytesIO(video)
    process = (
        ffmpeg
        .input('pipe:0', ss=start, t=duration)
        .output('pipe:1', format='mp4', vcodec='libx264', acodec='aac')
        .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
    )

    out, err = process.communicate(buffer.read())
    if process.returncode != 0:
        raise RuntimeError(f'ffmpeg error: {err.decode()}')
    return out

def trim_mp3(audio: bytes, start: int = 0, duration: int = 5) -> bytes:
    buffer = BytesIO(audio)
    process = (
        ffmpeg
        .input('pipe:0', ss=start, t=duration)
        .output('pipe:1', format='mp3', acodec='libmp3lame')
        .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
    )

    out, err = process.communicate(buffer.read())
    if process.returncode != 0:
        raise RuntimeError(f'ffmpeg error: {err.decode()}')
    return out

def compress(image: bytes, size: Tuple[int, int] = (150, 150)) -> BytesIO:
    buffer = BytesIO(image)
    img = Image.open(BytesIO(image))
    img = img.resize(size)
    img.save(buffer, format='png')
    buffer.seek(0)
    return buffer

@overload
def get_trace(trace_id: str, *, get_all: Literal[True]) -> Dict[str, str]:
    ...

@overload
def get_trace(trace_id: str, *, get_all: Literal[False] = ...) -> Optional[str]:
    ...

def get_trace(trace_id: str, *, get_all: bool = False) -> Union[Optional[str], Dict[str, str]]:
    with open('data/trace.json', 'rb') as file:
        traces = loads(file.read())
    if get_all:
        return traces
    return traces.get(trace_id)

def set_trace(trace_id: str, trace: str) -> bool:
    traces = get_trace('', get_all=True)
    if traces.get(trace_id):
        return False
    traces[trace_id] = trace
    with open('data/trace.json', 'wb') as file:
        file.write(dumps(traces))
    return True

def emoji_gen(amount: int) -> List[str]:
    return xs32.choice([
        e for e in list(EMOJI_DATA.keys())
        if '\u200d' not in e
        and e.isprintable()
        and not all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in e)
    ], length=amount)

def parse_doc(command: commands.Command, cooldowns: Cooldowns) -> dict[str, str]:
    error = 'No info available.'
    doc = cooldowns.callbacks[command.name][3]
    # if not doc:
    if not doc or True:
        return {
            'brief': error,
            'doc': error,
            'options': error
        }
    lines = [line.removeprefix('\t') for line in doc.splitlines()]
    current = 0
    separator_indexes: Dict[int, Tuple[int, List]] = {}
    for i, line in enumerate(lines):
        match line.strip():
            case '%0':
                separator_indexes[0] = (i, [])
                current = 0
            case '%1':
                separator_indexes[1] = (i, [])
                current = 1
            case '%2':
                separator_indexes[2] = (i, [])
                current = 2
            case _:
                if not current in separator_indexes:
                    separator_indexes[current] = (i, [])
                separator_indexes[current][1].append(line)
    brief = separator_indexes.get(0, (..., []))[1]
    description = separator_indexes.get(1, (..., []))[1]
    options = separator_indexes.get(2, (..., []))[1]
    return {
        'brief': ' '.join(brief or [error]),
        'doc': ' '.join(description or [error]),
        'options': '\n'.join(options or [error])
    }

def get_name(obj: Any, instance: Any) -> str | None:
    for name, value in vars(instance).items():
        if value is obj:
            return name
    return None

# from typing import TypeVar
# _T = TypeVar('_T')
# def optional[T](obj: Callable[[Any], T], value: Optional[Any], *args, default: Optional[_T] = None, **kwargs) -> Union[T, _T]:
#     return obj(value, *args, **kwargs) if value else default
# del _T
def optional[T](obj: Callable[[Any], T], value: Optional[Any], *args, default: Any = None, **kwargs) -> Union[T, Any]:
    return obj(value, *args, **kwargs) if value else default

def parse_arguments(key: str, value: Any, arg_type: Any):
    origin = get_origin(arg_type)
    args = get_args(arg_type)

    if origin is Union and type(None) in args:
        true_types = [arg for arg in args if arg is not type(None)]
        if value is None:
            return None
        elif len(true_types) == 1:
            arg_type = true_types[0]
        else:
            if not any(isinstance(value, t) for t in true_types):
                raise TypeError(f'Argument "{key}" must be one of {true_types}, got {type(value).__name__}')
            return value
    if isinstance(value, arg_type):
        return value
    try:
        return arg_type(value)
    except Exception:
        raise TypeError(f'Argument "{key}" must be of type {arg_type.__name__}, got {type(value).__name__}')
    

def parse_embeds(*embeds: TEmbed) -> List[discord.Embed]:
    _embeds: List[discord.Embed] = []
    for embed in embeds:
        color = embed.get('color')
        if isinstance(color, int):
            # Most likely discord.Color.value
            _color = discord.Color(color)
            color = '#{:02x}{:02x}{:02x}'.format(*_color.to_rgb())
        _embed = discord.Embed(
            title=embed.get('title'),
            description=embed.get('description'),
            color=optional(discord.Color.from_str, str(color)),
            url=embed.get('url'),
            type=embed.get('type', 'rich'),
            timestamp=optional(datetime.fromisoformat, embed.get('timestamp'))
        )
        footer = embed.get('footer')
        image = embed.get('image')
        thumbnail = embed.get('thumbnail')
        video = embed.get('video')
        author = embed.get('author')
        fields = embed.get('fields', [])

        if footer:
            _embed.set_footer(text=footer.get('text'), icon_url=footer.get('icon_url'))
        if image:
            _embed.set_image(url=image.get('url'))
        if thumbnail:
            _embed.set_thumbnail(url=thumbnail.get('url'))
        if video:
            # Too bad ig
            pass
        if author:
            _embed.set_author(
                name=author.get('name'),
                url=author.get('url'),
                icon_url=author.get('icon_url')
            )
        for field in fields:
            _embed.add_field(
                name=field.get('name'),
                value=field.get('value'),
                inline=field.get('inline', False)
            )
        _embeds.append(_embed)
    return _embeds

def gif() -> Iterator[str]:
    with open('data/gifs.txt', 'r') as file:
        gifs = [line.strip() for line in file.readlines()]
    while 1:
        for gif in gifs:
            yield gif

def now(**kwargs) -> datetime:
    dt = datetime.now(UTC)
    if kwargs:
        dt += timedelta(**kwargs)
    return dt

def fromtimestamp(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)

def check_members(author: Optional[Union[discord.Member, discord.User]], members: Sequence[discord.Member]) -> Tuple[List[discord.Member], List[discord.Member]]:
    skipped = []
    valid = []
    for member in members[:]:
        if member == member.guild.owner:
            skipped.append(member)
        elif member.top_role.position >= member.guild.me.top_role.position:
            skipped.append(member)
        elif member == author:
            skipped.append(member)
        else:
            valid.append(member)
    return valid, skipped

def convert_bytes(data: float, letter: str = 'B') -> tuple[float, str]:
    letters = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'YB']
    new = letters[letters.index(letter) + 1]
    if len(str(int(data // 1024))) < 4:
        return data / 1024, new
    return convert_bytes(data / 1024, new)