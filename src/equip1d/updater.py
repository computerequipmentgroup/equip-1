from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .settings import Equip1Settings


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    name: str
    body: str
    url: str
    asset_name: str | None
    asset_url: str | None
    published_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "name": self.name,
            "body": self.body,
            "url": self.url,
            "asset_name": self.asset_name,
            "asset_url": self.asset_url,
            "published_at": self.published_at,
        }


class AppUpdater:
    """Release-bundle updater for app-layer changes.

    The appliance image does not ship as a git checkout and does not include a
    Node build environment, so production self-updates install prebuilt release
    bundles rather than running `git pull` on the device. Bundles should contain
    the app payload either at the archive root or under `src/`:

    - equip1d/
    - uis/              (including uis/web/.output/public)
    - fonts/
    - requirements.txt
    """

    def __init__(self, settings: Equip1Settings | None = None):
        self.settings = settings or Equip1Settings()
        self.app_dir = Path(os.environ.get("EQUIP1_APP_DIR", "/opt/equip1")).expanduser()
        self.version_file = Path(
            os.environ.get("EQUIP1_VERSION_FILE", str(self.app_dir / "version.json"))
        ).expanduser()
        self.update_dir = Path(os.environ.get("EQUIP1_UPDATE_DIR", "/data/updates")).expanduser()
        self.repo = self._setting("repo", "computerequipmentgroup/equip-1", "EQUIP1_UPDATE_REPO")
        self.asset_name = self._setting("asset", "equip1-update.tar.gz", "EQUIP1_UPDATE_ASSET")
        self.token = os.environ.get("EQUIP1_UPDATE_TOKEN") or None
        self.latest: ReleaseInfo | None = None
        self.last_checked_at: str | None = None
        self.last_error: str | None = None

    def _setting(self, key: str, default: str, env: str) -> str:
        return self.settings.get("updates", key, default, env=env) or default

    def current_version(self) -> dict[str, Any]:
        try:
            return json.loads(self.version_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": "unknown", "tag": None, "commit": None}

    def status(self) -> dict[str, Any]:
        current = self.current_version()
        latest = self.latest.to_dict() if self.latest else None
        return {
            "current": current,
            "latest": latest,
            "available": self._is_available(current, self.latest),
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
            "repo": self.repo,
            "asset_name": self.asset_name,
        }

    def check(self) -> dict[str, Any]:
        self.last_error = None
        try:
            self.latest = self._fetch_latest_release()
            self.last_checked_at = datetime.now(timezone.utc).isoformat()
        except UpdateError as exc:
            self.last_error = str(exc)
        return self.status()

    def apply_latest(self) -> dict[str, Any]:
        status = self.check()
        if status.get("last_error"):
            raise UpdateError(str(status["last_error"]))
        latest = self.latest
        if latest is None:
            raise UpdateError("Could not check for updates")
        if not status.get("available"):
            return {**status, "applied": False, "message": "Already up to date"}
        if not latest.asset_url:
            raise UpdateError(f"Release {latest.tag} does not include an app update bundle")

        self.update_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.update_dir / latest.asset_name
        self._download(latest.asset_url, archive_path)
        self._install_bundle(archive_path, latest)
        self._schedule_restart()
        return {**self.status(), "applied": True, "message": "Update installed; restarting services"}

    def _fetch_latest_release(self) -> ReleaseInfo:
        if "/" not in self.repo:
            raise UpdateError("Update repo must be owner/name")
        data = self._request_json(f"https://api.github.com/repos/{self.repo}/releases/latest")
        assets = data.get("assets") if isinstance(data, dict) else None
        if not isinstance(assets, list):
            assets = []
        selected = None
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            if self._asset_matches(name, str(data.get("tag_name") or "")):
                selected = asset
                if name == self.asset_name:
                    break
        return ReleaseInfo(
            tag=str(data.get("tag_name") or ""),
            name=str(data.get("name") or data.get("tag_name") or ""),
            body=str(data.get("body") or ""),
            url=str(data.get("html_url") or ""),
            asset_name=str(selected.get("name")) if selected else None,
            asset_url=str(selected.get("browser_download_url")) if selected else None,
            published_at=data.get("published_at") if isinstance(data.get("published_at"), str) else None,
        )

    def _asset_matches(self, name: str, tag: str) -> bool:
        return name.strip() == self.asset_name

    def _request_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers=self._headers({"Accept": "application/vnd.github+json"}))
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise UpdateError(f"GitHub returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise UpdateError(f"Could not reach update server: {exc}") from exc

    def _download(self, url: str, target: Path) -> None:
        tmp = target.with_suffix(target.suffix + ".tmp")
        request = Request(url, headers=self._headers({"Accept": "application/octet-stream"}))
        try:
            with urlopen(request, timeout=30) as response, tmp.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            if tmp.stat().st_size <= 0:
                raise UpdateError("Downloaded update bundle is empty")
            tmp.replace(target)
        except HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise UpdateError(f"Download returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            raise UpdateError(f"Could not download update bundle: {exc}") from exc

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": "Equip-1-updater"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def _install_bundle(self, archive_path: Path, latest: ReleaseInfo) -> None:
        with tempfile.TemporaryDirectory(prefix="equip1-update-") as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            try:
                with tarfile.open(archive_path, "r:gz") as archive:
                    self._safe_extract(archive, tmp_dir)
            except (tarfile.TarError, OSError) as exc:
                raise UpdateError(f"Could not unpack update bundle: {exc}") from exc

            payload = self._find_payload_root(tmp_dir)
            if payload is None:
                raise UpdateError("Update bundle does not contain an Equip-1 app payload")

            backup_dir = self.update_dir / f"backup-{int(time.time())}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for name in ("equip1d", "uis", "fonts", "requirements.txt"):
                target = self.app_dir / name
                source = payload / name
                if not source.exists():
                    continue
                if target.exists():
                    shutil.move(str(target), str(backup_dir / name))
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

            version = self.current_version()
            version.update(
                {
                    "version": latest.tag,
                    "tag": latest.tag,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "release_url": latest.url,
                    "repo": self.repo,
                }
            )
            self.version_file.write_text(json.dumps(version, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
        destination = destination.resolve()
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if destination != target and destination not in target.parents:
                raise UpdateError("Update bundle contains unsafe paths")
        archive.extractall(destination)

    @staticmethod
    def _find_payload_root(root: Path) -> Path | None:
        candidates = [root, *root.iterdir()]
        for candidate in list(candidates):
            if candidate.is_dir():
                candidates.append(candidate / "src")
        for candidate in candidates:
            if (candidate / "equip1d").is_dir() and (candidate / "uis").is_dir():
                return candidate
        return None

    @staticmethod
    def _is_available(current: dict[str, Any], latest: ReleaseInfo | None) -> bool:
        if latest is None or not latest.tag or not latest.asset_url:
            return False
        current_tag = str(current.get("tag") or current.get("version") or "")
        return current_tag not in {latest.tag, f"v{latest.tag}", latest.tag.removeprefix("v")}

    @staticmethod
    def _schedule_restart() -> None:
        command = "sleep 1; /etc/init.d/S61equip1-oled restart >/dev/null 2>&1 || true; /etc/init.d/S60equip1d restart >/dev/null 2>&1 || true"
        subprocess.Popen(["/bin/sh", "-c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
