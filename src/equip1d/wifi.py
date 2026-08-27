from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .network import get_network_state
from .settings import Equip1Settings


class WifiConfigError(ValueError):
    pass


class WifiManager:
    def __init__(self, settings: Equip1Settings | None = None):
        self.settings = settings or Equip1Settings()
        self.wpa_config = Path(os.environ.get("EQUIP1_WPA_SUPPLICANT_CONF", "/etc/wpa_supplicant.conf")).expanduser()
        self.network_service = os.environ.get("EQUIP1_NETWORK_SERVICE", "/etc/init.d/S50network")
        self.oled_network_prompt = Path(os.environ.get("EQUIP1_OLED_NETWORK_PROMPT", "/tmp/equip1-oled-network-url-qr")).expanduser()
        self.port = int(os.environ.get("EQUIP1_PORT", "80"))

    def status(self) -> dict[str, Any]:
        network = get_network_state(self.port)
        mode = self.settings.get("network", "wifi_mode", "ap", env="EQUIP1_WIFI_MODE") or "ap"
        configured_ssid = self.settings.get("network", "client_ssid", None, env="EQUIP1_WIFI_CLIENT_SSID")
        return {
            "network": network.__dict__,
            "wifi_mode": mode,
            "client_configured": bool(configured_ssid),
            "client_ssid": configured_ssid,
            "setup_url": "http://10.42.0.1",
        }

    def scan(self) -> dict[str, Any]:
        iface = self.settings.get("network", "ap_iface", "wlan0", env="EQUIP1_AP_IFACE") or "wlan0"
        ssids = _scan_ssids(iface)
        return {**self.status(), "ssids": ssids}

    def configure_client(self, ssid: Any, password: Any) -> dict[str, Any]:
        clean_ssid = str(ssid or "").strip()
        clean_password = str(password or "")
        if not clean_ssid:
            raise WifiConfigError("Wi-Fi name is required")
        if len(clean_ssid.encode("utf-8")) > 32:
            raise WifiConfigError("Wi-Fi name is too long")
        if len(clean_password) < 8 or len(clean_password) > 63:
            raise WifiConfigError("Wi-Fi password must be 8–63 characters")

        self._write_wpa_supplicant(clean_ssid, clean_password)
        self.settings.save_value("network", "client_ssid", clean_ssid)
        self.settings.save_value("network", "wifi_mode", "client")
        os.environ["EQUIP1_WIFI_MODE"] = "client"
        os.environ["EQUIP1_WIFI_CLIENT_SSID"] = clean_ssid
        self._request_oled_network_screen()
        self._restart_network_background("client")
        return {**self.status(), "message": "Switching to Wi-Fi. Reconnect using the IP shown on OLED."}

    def use_access_point(self) -> dict[str, Any]:
        self.settings.save_value("network", "wifi_mode", "ap")
        os.environ["EQUIP1_WIFI_MODE"] = "ap"
        self._restart_network_background("ap")
        return {**self.status(), "message": "Switching back to the Equip-1 access point."}

    def _write_wpa_supplicant(self, ssid: str, password: str) -> None:
        self.wpa_config.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(
            [
                "ctrl_interface=/var/run/wpa_supplicant",
                "update_config=0",
                "",
                "network={",
                f"    ssid={_wpa_quote(ssid)}",
                f"    psk={_wpa_quote(password)}",
                "    key_mgmt=WPA-PSK",
                "    scan_ssid=1",
                "}",
                "",
            ]
        )
        tmp = self.wpa_config.with_name(f".{self.wpa_config.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, self.wpa_config)

    def _request_oled_network_screen(self) -> None:
        try:
            self.oled_network_prompt.write_text("url\n", encoding="utf-8")
        except OSError:
            pass

    def _restart_network_background(self, wifi_mode: str) -> None:
        command = f"sleep 1; {shlex.quote(self.network_service)} restart >/dev/null 2>&1 || true"
        env = os.environ.copy()
        # equip1d is started by S60equip1d, which exports the network mode it
        # read at boot. If S50network inherits that stale value, it ignores the
        # newly saved INI value and simply restarts the old mode.
        env["EQUIP1_WIFI_MODE"] = wifi_mode
        subprocess.Popen(["/bin/sh", "-c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def _wpa_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _scan_ssids(iface: str) -> list[str]:
    commands = [
        ["iw", "dev", iface, "scan", "ap-force"],
        ["iw", "dev", iface, "scan"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=12)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        ssids = _parse_iw_scan(result.stdout)
        if ssids:
            return ssids
    return []


def _parse_iw_scan(output: str) -> list[str]:
    seen: set[str] = set()
    ssids: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("SSID:"):
            continue
        ssid = stripped.split(":", 1)[1].strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        ssids.append(ssid)
    return sorted(ssids, key=str.casefold)
