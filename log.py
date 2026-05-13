
import logging
import os
import sys

from io import TextIOWrapper
from colorama import Fore
from datetime import datetime, UTC
from typing import Literal, Any, Mapping


def create_logger(name: str, *, level: int = logging.INFO, file_log: bool = False) -> None:
    logger = logging.getLogger()
    utf8 = TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    console_handler = logging.StreamHandler(utf8)
    formatter = Formatter(False)
    console_handler.setFormatter(Formatter(True))
    console_handler.setLevel(level)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    
    if file_log:
        os.makedirs('logs', exist_ok=True)
        filename = 'logs/app_{}{}.log'
        filename = filename.format(name, datetime.now(UTC).strftime(r'%y-%m-%d_%H-%M-%S'))

        file_handler = logging.FileHandler(filename=filename, encoding='utf-8')
        file_handler2 = logging.FileHandler(filename=f'logs/app_{name}.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler2.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        file_handler2.setLevel(level)
        logger.addHandler(file_handler)
        logger.addHandler(file_handler2)


class Formatter(logging.Formatter):
    LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.WARN,
        logging.ERROR,
        logging.CRITICAL
    ]
    COLORS = [
        (logging.DEBUG, Fore.LIGHTBLACK_EX),
        (logging.INFO, Fore.LIGHTCYAN_EX),
        (logging.WARNING, Fore.YELLOW),
        (logging.WARN, Fore.YELLOW),
        (logging.ERROR, Fore.RED),
        (logging.CRITICAL, Fore.LIGHTRED_EX)
    ]
    FORMATS = {
        level: logging.Formatter(
            f'%(asctime)s [ %(levelname)s ] %(name)s: %(message)s',
            '%Y-%m-%d %H:%M:%S',
        )
        for level in LEVELS
    }

    def __init__(self, color: bool, fmt: str | None = None, datefmt: str | None = None, style: Literal['%'] | Literal['{'] | Literal['$'] = "%", validate: bool = True, *, defaults: Mapping[str, Any] | None = None) -> None:
        if color:
            self.FORMATS = {
                level: logging.Formatter(
                    f'{Fore.LIGHTBLACK_EX}%(asctime)s{Fore.RESET} [ {color}%(levelname)s{Fore.RESET} ] {Fore.MAGENTA}%(name)s: {color}%(message)s{Fore.RESET}',
                    '%Y-%m-%d %H:%M:%S',
                )
                for level, color in self.COLORS
            }
        super().__init__(fmt, datefmt, style, validate, defaults=defaults)

    def format(self, record: logging.LogRecord):
        formatter = self.FORMATS.get(record.levelno)
        record.levelname = record.levelname.center(8)

        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]
        
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = text

        output = formatter.format(record)
        record.exc_text = None
        return output