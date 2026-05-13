import requests
import random
import math
import string
import time
import threading
from itertools import combinations
from typing import TextIO

failed = []
lock = threading.Lock()

def user_gen(prefix: str, amount_digits: int, amount_characters: int):
    letters = string.ascii_lowercase
    digits = string.digits
    while True:
        yield prefix + ''.join(random.choices(letters + digits, k=amount_characters - len(prefix)))
    while 1:
        for item in failed:
            yield item

def proxy_gen(proxies: list[str]):
    i = 0
    while 1:
        yield proxies[i % len(proxies)]
        i += 1

def check_username(username: str, proxy: str | None) -> bool | None:
    session = requests.Session()
    proxies = {}
    if proxy:
        if not proxy.startswith('http://') and not proxy.startswith('https://'):
            proxy = 'http://' + proxy
        proxies = {
            'http': proxy,
            'https': proxy
        }
        
    try:
        session.proxies = proxies
        response = session.post(
            'https://discord.com/api/unique-username/username-attempt-unauthed',
            json={
                'username': username
            },
            timeout=10
        )
    except requests.exceptions.ProxyError as exc:
        # print(f'Bad proxy: {proxy}.')
        return None
    except Exception as exc:
        # print(exc, proxy)
        return None
    if response.status_code != 200:
        json = response.json()
        # print(json)
        if not proxy_file:
            retry_after = json['retry_after']
            print(f'Sleeping... Cya in {retry_after} seconds')
            time.sleep(retry_after)
        failed.append(username)
        return None
    if username in failed:
        failed.remove(username)
    return not response.json()['taken']

def task(file: TextIO):
    with lock:
        username = next(user)
    result = check_username(username, proxy_file and next(proxy) or None)
    if result:
        print(f'HIT! {username}')
        file.write(username + '\n')
        file.flush()
    elif result is None:
        print(f'Skipping {username}')
    else:
        print(f'{username} is taken..')

prefix = input('Enter username prefix: ')
amount_characters = int(input('Amount of characters: '))
amount_digits = int(input('Amount of digits: '))
delay = float(input('Delay between checking usernames: ') or 0)
proxy_file = input('Enter the path of your proxy file [format - 1 proxy per line]: ')
proxies = []

if proxy_file:
    with open(proxy_file) as file:
        proxies = [proxy.strip() for proxy in file.readlines()]

proxy = proxy_gen(proxies)
user = user_gen(prefix, amount_digits, amount_characters)

print('Starting. Valid usernames will be saved to output.txt')
with open('output.txt', 'w') as file:
    try:
        while 1:
            thread = threading.Thread(target=task, args=(file,))
            thread.start()
            # CPU saver
            time.sleep(delay)
    except KeyboardInterrupt:
        print('Operation cancelled')