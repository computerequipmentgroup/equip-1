from __future__ import annotations

import html
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn


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


def _start_captive_portal() -> None:
    if os.environ.get("FIREHAT_CAPTIVE_ENABLED", "1") in {"0", "false", "False", "no"}:
        return

    host = os.environ.get("FIREHAT_CAPTIVE_HOST", "0.0.0.0")
    port = int(os.environ.get("FIREHAT_CAPTIVE_PORT", "80"))
    dashboard_url = os.environ.get("FIREHAT_CAPTIVE_DASHBOARD_URL")
    if not dashboard_url:
        ap_ip = os.environ.get("FIREHAT_AP_IP", "10.42.0.1")
        dashboard_port = int(os.environ.get("FIREHAT_PORT", "8000"))
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
    host = os.environ.get("FIREHAT_HOST", "0.0.0.0")
    port = int(os.environ.get("FIREHAT_PORT", "8000"))
    _start_captive_portal()
    uvicorn.run("firehatd.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
