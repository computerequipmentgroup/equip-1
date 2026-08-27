from __future__ import annotations

import html
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn

from .logging import debug_enabled, log, should_log
from .settings import Equip1Settings


class CaptivePortalHandler(BaseHTTPRequestHandler):
    server_version = "Equip1Captive/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        self._redirect_to_dashboard()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler name
        self.send_response(302)
        self.send_header("Location", self._dashboard_url())
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        self._redirect_to_dashboard()

    def log_message(self, fmt: str, *args: object) -> None:
        if debug_enabled() or os.environ.get("EQUIP1_CAPTIVE_DEBUG") == "1":
            super().log_message(fmt, *args)

    def _dashboard_url(self) -> str:
        return getattr(self.server, "dashboard_url", "http://10.42.0.1/")

    def _redirect_to_dashboard(self) -> None:
        dashboard_url = self._dashboard_url()
        body = _portal_page(dashboard_url).encode("utf-8")
        # Captive-network probes expect specific success responses from Apple,
        # Android, Windows, etc. A redirect instead marks the AP as captive and
        # opens the OS captive assistant directly on the Equip-1 dashboard.
        self.send_response(302)
        self.send_header("Location", dashboard_url)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _portal_page(dashboard_url: str) -> str:
    escaped_url = html.escape(dashboard_url, quote=True)
    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta http-equiv=\"refresh\" content=\"0;url={escaped_url}\">
  <title>Open Equip-1</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
    a {{ display: inline-block; padding: 0.8rem 1rem; background: #111; color: #fff; border-radius: 0.6rem; text-decoration: none; }}
  </style>
</head>
<body>
  <h1>Equip-1</h1>
  <p>Opening the dashboard…</p>
  <p><a href=\"{escaped_url}\">Open Dashboard</a></p>
</body>
</html>
"""


def _start_captive_portal(settings: Equip1Settings) -> None:
    wifi_mode = (settings.get("network", "wifi_mode", "ap", env="EQUIP1_WIFI_MODE") or "ap").strip().lower()
    if wifi_mode != "ap" or not settings.get_bool(
        "network", "captive_enabled", False, env="EQUIP1_CAPTIVE_ENABLED"
    ):
        return

    host = settings.get("network", "captive_host", "0.0.0.0", env="EQUIP1_CAPTIVE_HOST") or "0.0.0.0"
    port = settings.get_int("network", "captive_port", 80, env="EQUIP1_CAPTIVE_PORT")
    dashboard_url = settings.get("network", "captive_dashboard_url", None, env="EQUIP1_CAPTIVE_DASHBOARD_URL")
    if not dashboard_url:
        ap_ip = settings.get("network", "ap_ip", "10.42.0.1", env="EQUIP1_AP_IP") or "10.42.0.1"
        dashboard_port = settings.get_int("network", "port", 80, env="EQUIP1_PORT")
        port_suffix = "" if dashboard_port == 80 else f":{dashboard_port}"
        dashboard_url = f"http://{ap_ip}{port_suffix}/"

    try:
        server = ThreadingHTTPServer((host, port), CaptivePortalHandler)
    except OSError as exc:
        log(f"Warning: captive portal could not bind {host}:{port}: {exc}", level="warning")
        return

    server.dashboard_url = dashboard_url  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="equip1-captive", daemon=True)
    thread.start()
    log(f"Captive portal listening on {host}:{port}, redirecting to {dashboard_url}")


def main() -> None:
    settings = Equip1Settings()
    host = settings.get("network", "host", "0.0.0.0", env="EQUIP1_HOST") or "0.0.0.0"
    port = settings.get_int("network", "port", 80, env="EQUIP1_PORT")
    _start_captive_portal(settings)
    uvicorn_log_level = "critical" if not should_log("info") else "debug" if should_log("debug") else "info"
    uvicorn.run("equip1d.api:app", host=host, port=port, log_level=uvicorn_log_level)


if __name__ == "__main__":
    main()
