from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ApiError(RuntimeError):
    pass


@dataclass
class ApiResult:
    ok: bool
    data: dict[str, Any] | list[Any] | None = None
    error: str | None = None


class Equip1ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000/api", timeout: float = 0.7):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_ok_at: float | None = None
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self.last_ok_at is not None and (time.time() - self.last_ok_at) < 3.0

    def get_state(self) -> ApiResult:
        return self._request("GET", "/state")

    def command(self, name: str) -> ApiResult:
        return self._request("POST", f"/commands/{name}")

    def post_json(self, path: str, payload: dict[str, Any]) -> ApiResult:
        return self._request("POST", path, payload=payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> ApiResult:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"{self.base_url}{path}", data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body) if body else None
                self.last_ok_at = time.time()
                self.last_error = None
                return ApiResult(ok=True, data=data)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.last_error = detail or str(exc)
            return ApiResult(ok=False, error=self.last_error)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = str(exc)
            return ApiResult(ok=False, error=self.last_error)
