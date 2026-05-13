from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass
from aiohttp import FormData

from .exceptions import Unauthorized
from .http import HTTP, Request
from .typed import *


@dataclass
class Display:
    backup: bool
    cron: bool
    hardware: bool
    ip: bool
    livedata: bool
    novnc: bool
    traffic: bool


@dataclass
class Product:
    additional_traffic: int
    cores: int
    created_at: datetime
    disk: int
    hostname: str
    id: str
    max: str
    memory: int
    node_id: str
    os: str
    packet: str
    proxmoxid: int
    password: str
    service_id: str
    status: str
    uplink: int
    user: str


@dataclass
class OS:
    id: str
    name: str
    type: str
    proxmox_id: int


@dataclass
class IPv4Data:
    ip: str
    gateway: str
    netmask: str
    rdns: str
    subnet_id: int


@dataclass
class IPv6Data:
    first_ip: str
    gateway: str
    netmash: str
    subnet_id: str


@dataclass
class Backup:
    id: str
    name: str
    created_at: datetime
    proxmox_id: str


@dataclass
class Cron:
    id: str
    name: str
    action: str
    created_at: datetime
    expression: str
    kvm_id: str
    next_execute_at: datetime
    status: int


class Service:
    _http: HTTP
    display: Display
    product: Product
    os: List[OS]
    ipv4: List[IPv4Data]
    ipv6: List[IPv6Data]
    backups: List[Backup]
    crons: List[Cron]
    id: str
    name: str
    created_at: datetime
    expires_at: datetime
    is_deleted: bool
    price: float
    preorder: bool
    productdisplay: str

    @classmethod
    def from_data(cls, data: ServiceResponse, http: HTTP):
        self = cls()
        self._http = http
        self.id = data['id']
        self.name = data['name']
        self.created_at = datetime.fromtimestamp(data['created_on'])
        self.expires_at = datetime.fromtimestamp(data['expire_at'])
        self.is_deleted = bool(data['deletedone'])
        self.price = float(data['price'])
        self.preorder = bool(data['preorder'])
        self.productdisplay = data['productdisplay']
        return self
    
    async def update(self) -> None:
        await self.get_service()
        await self.get_os()
        await self.get_ips()
        await self.get_backups()
        await self.get_crons()

    async def get_service(self) -> None:
        request = Request('GET', f'/service/{self.id}')
        response = await self._http.request(request)
        service_data: ServiceInfoResponse = await response.json()
        _display = service_data['display']
        _product = service_data['product']

        for key, value in _display.items():
            _display[key] = bool(value)

        display = Display(
            _display['backup'],
            _display['cron'],
            _display['hardware'],
            _display['ip'],
            _display['livedata'],
            _display['novnc'],
            _display['traffic'],
        )
        product = Product(
            _product['additionaltraffic'],
            _product['cores'],
            datetime.fromisoformat(_product['created_on']),
            _product['disk'],
            _product['hostname'],
            _product['id'],
            _product['mac'],
            _product['memory'],
            _product['nodeid'],
            _product['os'],
            _product['packet'],
            _product['proxmoxid'],
            _product['password'],
            _product['serviceid'],
            _product['status'],
            _product['uplink'],
            _product['user']
        )
        self.display = display
        self.product = product

    async def get_status(self) -> None:
        request = Request('GET', f'/service/{self.id}/status')
        response = await self._http.request(request)
        data = await response.json()
        self.product.status = data['status']

    async def get_os(self) -> None:
        request = Request('GET', f'/service/{self.id}/os')
        response = await self._http.request(request)
        data: List[KVMLineOsResponse] = await response.json()
        self.os = []
        for _os in data:
            os = OS(
                _os['id'],
                _os['displayname'],
                _os['type'],
                _os['proxmoxid']
            )
            self.os.append(os)

    async def get_ips(self) -> None:
        request = Request('GET', f'/service/{self.id}/ip')
        response = await self._http.request(request)
        ip_data: ServiceIPResponse = await response.json()
        _ipv4_data = ip_data['ipv4']
        _ipv6_data = ip_data['ipv6']
        self.ipv4 = []
        self.ipv6 = []

        for _ipv4 in _ipv4_data:
            ipv4 = IPv4Data(
                _ipv4['ip'],
                _ipv4['gw'],
                _ipv4['netmask'],
                _ipv4['rdns'],
                _ipv4['subnet']
            )
            self.ipv4.append(ipv4)

        for _ipv6 in _ipv6_data:
            ipv6 = IPv6Data(
                _ipv6['firstip'],
                _ipv6['gw'],
                _ipv6['netmask'],
                _ipv6['subnet']
            )
            self.ipv6.append(ipv6)

    async def update_rdns(self, ip: str, rdns: str) -> None:
        form = FormData()
        form.add_field('rdns', rdns)
        request = Request('POST', f'/service/{self.id}/ip/{ip}', data=form)
        await self._http.request(request)
        for ipv4 in self.ipv4.copy():
            ipv4.rdns = rdns

    async def stop(self) -> None:
        request = Request('POST', f'/service/{self.id}/stop')
        await self._http.request(request)
        self.product.status = 'stopped'

    async def start(self) -> None:
        request = Request('POST', f'/service/{self.id}/stop')
        await self._http.request(request)
        self.product.status = 'running'

    async def shutdown(self) -> None:
        request = Request('POST', f'/service/{self.id}/shutdown')
        await self._http.request(request)
        self.product.status = 'stopped'

    async def restart(self) -> None:
        request = Request('POST', f'/service/{self.id}/restart')
        await self._http.request(request)

    async def reinstall(self, os: str) -> None:
        form = FormData()
        form.add_field('OS', os)
        request = Request('POST', f'/service/{self.id}/reinstall', data=form)
        await self._http.request(request)
        self.product.status = 'reinstalling'

    async def get_backups(self) -> None:        
        request = Request('GET', f'/service/{self.id}/backup')
        response = await self._http.request(request)
        backup_data: List[ServiceBackupResponse] = await response.json()
        self.backups = []

        for _backup in backup_data:
            # Absolute retards
            stupid_format = _backup['created_on']
            time, date = stupid_format.split()
            f, c, k = time.split(':')
            y, o, u = date.split('.')
            time = ':'.join([k, c, f])
            date = '-'.join([u, o, y])
            fixed = f'{date} {time}'
            date = datetime.fromisoformat(fixed)
            backup = Backup(
                _backup['id'],
                _backup['backupname'],
                date,
                _backup['proxmoxid']
            )
            self.backups.append(backup)

    async def create_backups(self) -> None:
        request = Request('POST', f'/service/{self.id}/backup')
        await self._http.request(request)
        await self.get_backups()

    async def get_crons(self) -> None:
        request = Request('GET', f'/service/{self.id}/cron')
        response = await self._http.request(request)
        data: List[ServiceCronResponse] = await response.json()
        self.crons = []
        for _cron in data:
            cron = Cron(
                _cron['id'],
                _cron['dispalyname'],
                _cron['action'],
                datetime.fromisoformat(_cron['created_on']),
                _cron['expression'],
                _cron['kvmid'],
                datetime.fromisoformat(_cron['nextexecute']),
                _cron['status']
            )
            self.crons.append(cron)

    async def create_cron(self, name: str, action: str, expression: str) -> None:
        form = FormData()
        form.add_field('name', name)
        form.add_field('action', action)
        form.add_field('expression', expression)
        request = Request('POST', f'/service/{self.id}/cron', data=form)
        await self._http.request(request)
        await self.get_crons()

    async def update_cron(self, cron_id: str, name: str, action: str, expression: str) -> None:
        form = FormData()
        form.add_field('name', name)
        form.add_field('action', action)
        form.add_field('expression', expression)
        request = Request('POST', f'/service/{self.id}/cron/{cron_id}', data=form)
        await self._http.request(request)

        for cron in self.crons.copy():
            if cron.id == cron_id:
                cron.name = name
                cron.action = action
                cron.expression = expression
                break

    async def delete_cron(self, cron_id: str) -> None:
        request = Request('DELETE', f'/service/{self.id}/cron/{cron_id}/delete')
        await self._http.request(request)
        for cron in self.crons.copy():
            if cron.id == cron_id:
                self.crons.remove(cron)
                break

    async def delete_backup(self, backup_id: str) -> None:
        form = FormData()
        form.add_field('backup', backup_id)
        request = Request('POST', f'/service/{self.id}/backup/delete', data=form)
        await self._http.request(request)
        for backup in self.backups:
            if backup.id == backup_id:
                self.backups.remove(backup)

    async def restore_backup(self, backup_id: str) -> None:
        form = FormData()
        form.add_field('backup', backup_id)
        request = Request('POST', f'/service/{self.id}/backup/restore', data=form)
        await self._http.request(request)

    async def extend_service(self, days: int, credit: int) -> None:
        form = FormData()
        form.add_field('days', days)
        form.add_field('credit', credit)
        request = Request('POST', f'/service/{self.id}/extend', data=form)
        response = await self._http.request(request)
        data: ServiceExtendResponse = await response.json()
        self.id = data['id']

    async def hide_service(self) -> Service:
        request = Request('POST', f'/service/{self.id}/hide')
        response = await self._http.request(request)
        data: ServiceResponse = await response.json()
        return Service.from_data(data, self._http)

    
class Datalix:
    http: HTTP
    services: List[Service]
    authorization_failure: Optional[bool]

    def __init__(self) -> None:
        self.services = []
        self.authorization_failure = None

    async def start(self, token: str) -> None:
        self.http = HTTP(token)
        await self.fetch_services()

    async def fetch_services(self, *, auto_update: bool = False):
        try:
            request = Request('GET', '/service/list')
        except Unauthorized:
            self.authorization_failure = True
            return
        self.authorization_failure = False

        response = await self.http.request(request)
        json = await response.json()
        for data in json:
            service = Service.from_data(data, self.http)
            if auto_update:
                await service.update()
            self.services.append(service)

    async def close(self) -> None:
        if not self.http.session.closed:
            await self.http.session.close()

    async def __aenter__(self, *args):
        pass

    async def __aexit__(self, *args):
        await self.close()