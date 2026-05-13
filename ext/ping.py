from requests import Session
import time
import pymysql

CHECK = {
    'host': 'http://node2.lunes.host',
    'worker1': 'http://node66.lunes.host:3050',
    'worker2': 'http://node65.lunes.host:3086',
    'worker3': 'http://node66.lunes.host:3294',
    'database': {
        "host": "134.98.130.43",
        "user": "admin",
        "password": "e7rtaGG2Yo+NWZIqdveENQ==",
        "database": "fluc",
        "server": 183723
    }
}
MAX_NODES = 10
BASE = 'https://check-host.net/{}'
CROSSMARK = '<:crossmark:1475897574035685576>'
CHECKMARK = '<:checkmark:1475897532331855893>'
REPORT_WEBHOOK = 'https://discord.com/api/webhooks/1475461449919762515/COjb_F_5lnW9WyFAv6RL5iFIE4F7uFKF0o_2h15sSynGT_TU0kvx95HDOCxpwQDQ5jsi'
webhook_session = Session()

def check():
    session = Session()
    lines = []
    fails = 0
    for name, url in CHECK.items():
        start = time.perf_counter()
        if name == 'database':
            try:
                conn = pymysql.connect(
                    host=url['host'],
                    user=url['user'],
                    password=url['password'],
                    database=url['database'],
                    connect_timeout=10
                )
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    cursor.fetchone()
                end = time.perf_counter()
                lines.append(f'{CHECKMARK} {name} - {round((end - start) * 1000, 2)}ms')
            except Exception:
                lines.append('{CROSSMARK} {name} - TIMEOUT')
        else:
            try:
                session.get(url, timeout=10)
                end = time.perf_counter()
                lines.append(f'{CHECKMARK} {name} - {round((end - start) * 1000, 2)}ms')
            except Exception:
                fails += 1
                lines.append(f'{CROSSMARK} {name} - TIMEOUT')
    return lines, fails

def report(lines: list[str], fails: int):
    description = '\n'.join(lines)
    if fails == len(lines):
        description = f'Service not operational\n' + description
        color = 0xff0000
    elif fails:
        description = f'{fails} services are not operational\n' + description
        color = 0xffff00
    else:
        description = f'All services operational\n' + description
        color = 0x00ff00
    
    embed = {
        'title': 'Status Report',
        'description': description ,
        'color': color
    }
    _mention = bool(fails)
    message = {
        'content': _mention and '<@&1476229172274790474>' or '',
        'embeds': [embed]
    }
    webhook_session.post(REPORT_WEBHOOK, json=message)

while True:
    try:
        lines, failed = check()
        if lines:
            report(lines, failed)
    except Exception:
        pass
    time.sleep(60)
