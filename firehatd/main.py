from __future__ import annotations

import html
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn

from .settings import FirehatSettings


class CaptivePortalHandler(BaseHTTPRequestHandler):
    server_version = "FirehatCaptive/0.1"

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
        if os.environ.get("FIREHAT_CAPTIVE_DEBUG") == "1":
            super().log_message(fmt, *args)

    def _dashboard_url(self) -> str:
        return getattr(self.server, "dashboard_url", "http://10.42.0.1:8000/")

    def _redirect_to_dashboard(self) -> None:
        dashboard_url = self._dashboard_url()
        body = _portal_page(dashboard_url).encode("utf-8")
        # Captive-network probes expect specific success responses from Apple,
        # Android, Windows, etc. A redirect instead marks the AP as captive and
        # opens the OS captive assistant directly on the Firehat dashboard.
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
  <title>Open Firehat</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; }}
    a {{ display: inline-block; padding: 0.8rem 1rem; background: #111; color: #fff; border-radius: 0.6rem; text-decoration: none; }}
  </style>
</head>
<body>
  <h1>Firehat</h1>
  <p>Opening the dashboard…</p>
  <p><a href=\"{escaped_url}\">Open Dashboard</a></p>
</body>
</html>
"""


def _start_captive_portal(settings: FirehatSettings) -> None:
    wifi_mode = (settings.get("network", "wifi_mode", "ap", env="FIREHAT_WIFI_MODE") or "ap").strip().lower()
    if wifi_mode != "ap" or not settings.get_bool(
        "network", "captive_enabled", True, env="FIREHAT_CAPTIVE_ENABLED"
    ):
        return

    host = settings.get("network", "captive_host", "0.0.0.0", env="FIREHAT_CAPTIVE_HOST") or "0.0.0.0"
    port = settings.get_int("network", "captive_port", 80, env="FIREHAT_CAPTIVE_PORT")
    dashboard_url = settings.get("network", "captive_dashboard_url", None, env="FIREHAT_CAPTIVE_DASHBOARD_URL")
    if not dashboard_url:
        ap_ip = settings.get("network", "ap_ip", "10.42.0.1", env="FIREHAT_AP_IP") or "10.42.0.1"
        dashboard_port = settings.get_int("network", "port", 8000, env="FIREHAT_PORT")
        dashboard_url = f"http://{ap_ip}:{dashboard_port}/"

    try:
        server = ThreadingHTTPServer((host, port), CaptivePortalHandler)
    except OSError as exc:
        print(f"Warning: captive portal could not bind {host}:{port}: {exc}", flush=True)
        return

    server.dashboard_url = dashboard_url  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="firehat-captive", daemon=True)
    thread.start()
    print(f"Captive portal listening on {host}:{port}, redirecting to {dashboard_url}", flush=True)


def main() -> None:
    settings = FirehatSettings()
    host = settings.get("network", "host", "0.0.0.0", env="FIREHAT_HOST") or "0.0.0.0"
    port = settings.get_int("network", "port", 8000, env="FIREHAT_PORT")
    _start_captive_portal(settings)
    uvicorn.run("firehatd.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
