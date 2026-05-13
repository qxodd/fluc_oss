from typing import TypedDict, List


class ServiceResponse(TypedDict):
    id: str
    created_on: int
    delete_at: int
    deletedone: int
    expire_at: int
    name: str
    preorder: int
    price: str
    productdisplay: str


class DisplayResponse(TypedDict):
    backup: bool
    cron: bool
    hardware: bool
    ip: bool
    livedata: bool
    novnc: bool
    traffic: bool


class ProductResponse(TypedDict):
    additionaltraffic: int
    cores: int
    created_on: str
    disk: int
    hostname: str
    id: str
    mac: str
    memory: int
    nodeid: str
    os: str
    packet: str
    proxmoxid: int
    password: str
    serviceid: str
    status: str
    uplink: int
    user: str


class ServiceInfoResponse(TypedDict):
    display: DisplayResponse
    product: ProductResponse
    service: ServiceResponse


class KVMLineOsResponse(TypedDict):
    id: str
    displayname: str
    proxmoxid: int
    type: str


class IPv4Response(TypedDict):
    gw: str
    ip: str
    netmask: str
    rdns: str
    # subnetid: int
    # This api is ran on retards
    subnet: int


class IPv6Response(TypedDict):
    firstip: str
    gw: str
    netmask: str
    subnet: str
    # subnetid: int


class ServiceIPResponse(TypedDict):
    ipv4: List[IPv4Response]
    ipv6: List[IPv6Response]


class ServiceBackupResponse(TypedDict):
    backupname: str
    created_on: str
    displayname: str
    id: str
    proxmoxid: str


class ServiceCronResponse(TypedDict):
    action: str
    created_on: str
    dispalyname: str
    expression: str
    id: str
    kvmid: str
    nextexecute: str
    status: int


class ServiceExtendResponse(TypedDict):
    id: str