import string
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

tries = []
proxy = {
    'https': 'http://3tin3ehX:svBHNNaL@lite.flashproxy.io:6969'
}

def user_gen():
    chars = list(string.ascii_lowercase)
    random.shuffle(chars)
    while True:
        index = [random.randint(0, len(chars) - 1) for _ in 'abcd']
        if index in tries:
            continue
        tries.append(index)
        yield chars[index[0]] + chars[index[1]] + chars[index[2]] + chars[index[3]]

gen = user_gen()
session = requests.session()
session.proxies = proxy

def check(username):
    try:
        response = session.post(
            'https://discord.com/api/unique-username/username-attempt-unauthed',
            json={ 'username': username }
        )
    except:
        try:
            tries.remove(username)
        finally:
            return
    if not response.ok:
        # print(f'Failed: {response.status_code} {username}')
        try:
            tries.remove(username)
        finally:
            return
    data = response.json()
    if not data['taken']:
        file.write(f'{username}\n'.encode())
    #     print(f'Sniped: {username}')
    # else:
    #     print(f'Failed: {response.status_code} {username}')

with open('available.txt', 'wb', buffering=0) as file, ThreadPoolExecutor(max_workers=250) as executor:
    futures = []
    while True:
        # if True:
        #     executor.submit(check, next(gen))
        # for _ in range(100):
        #     futures.append(executor.submit(check, next(gen)))
        # for fut in as_completed(futures):
        #     fut.result()
        executor.submit(check, next(gen))
        import time
        time.sleep(0.01)