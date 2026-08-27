from __future__ import annotations

import socket
import subprocess

from .models import NetworkState
from .settings import Equip1Settings

def _http_url(host: str, port: int) -> str:
    suffix = "" if port == 80 else f":{port}"
    return f"http://{host}{suffix}"


def _strip_cidr(value: str) -> str:
    return value.split("/", 1)[0]


def get_interface_ipv4(iface: str) -> str | None:
    """Return the first IPv4 address assigned to an interface, if Linux `ip` exists."""
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", iface],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            idx = parts.index("inet")
            if idx + 1 < len(parts):
                return _strip_cidr(parts[idx + 1])
    return None


def get_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def get_hostname() -> str:
    return socket.gethostname()


def get_network_state(port: int) -> NetworkState:
    settings = Equip1Settings()
    hostname = get_hostname()
    lan_ip = get_lan_ip()

    wifi_mode = (settings.get("network", "wifi_mode", "ap", env="EQUIP1_WIFI_MODE") or "ap").strip().lower()
    ap_enabled = wifi_mode == "ap" and settings.get_bool(
        "network", "ap_enabled", True, env="EQUIP1_AP_ENABLED"
    )
    ap_iface = settings.get("network", "ap_iface", "wlan0", env="EQUIP1_AP_IFACE") if ap_enabled else None
    ap_ssid = settings.get("network", "ap_ssid", "Equip-1", env="EQUIP1_AP_SSID") if ap_enabled else None
    ap_password = settings.get("network", "ap_password", "firesecret", env="EQUIP1_AP_PASSWORD") if ap_enabled else None
    client_ssid = settings.get("network", "client_ssid", None, env="EQUIP1_WIFI_CLIENT_SSID")
    ap_ip = get_interface_ipv4(ap_iface) if ap_iface else None

    if ap_ip:
        return NetworkState(
            ip=ap_ip,
            hostname=hostname,
            url=_http_url(ap_ip, port),
            mode="access_point",
            ssid=ap_ssid,
            password=ap_password,
            ap_ip=ap_ip,
            iface=ap_iface,
        )

    if lan_ip:
        return NetworkState(
            ip=lan_ip,
            hostname=hostname,
            url=_http_url(lan_ip, port),
            mode="lan",
            ssid=client_ssid,
            password=None,
            ap_ip=None,
            iface=ap_iface,
        )

    return NetworkState(
        ip=None,
        hostname=hostname,
        url=None,
        mode="offline",
        ssid=ap_ssid,
        password=ap_password,
        ap_ip=None,
        iface=ap_iface,
    )
