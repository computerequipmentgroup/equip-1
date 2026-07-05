from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DV_BYTES_PER_MINUTE = 216 * 1024 * 1024
CAPTURE_EXTENSIONS = {".dv", ".avi", ".mov", ".mp4", ".mkv"}
THUMBNAIL_EXTENSION = ".jpg"


@dataclass(frozen=True)
class StorageSnapshot:
    capture_dir: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    recording_minutes_available: int


class StorageManager:
    def __init__(self, capture_dir: str | os.PathLike[str]):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> StorageSnapshot:
        total, used, free = shutil.disk_usage(self.capture_dir)
        return StorageSnapshot(
            capture_dir=str(self.capture_dir),
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            recording_minutes_available=int(free / DV_BYTES_PER_MINUTE),
        )

    def has_recording_space(self, minimum_minutes: int = 1) -> bool:
        return self.snapshot().recording_minutes_available >= minimum_minutes

    def list_captures(self) -> list[dict]:
        captures: list[dict] = []
        for path in sorted(self.capture_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in CAPTURE_EXTENSIONS:
                continue
            stat = path.stat()
            thumbnail_path = self._thumbnail_path_for_capture(path)
            capture = {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "download_url": f"/api/captures/{path.name}/download",
            }
            if thumbnail_path.exists():
                capture["thumbnail_url"] = f"/api/captures/{path.name}/thumbnail"
            captures.append(capture)
        return captures

    def capture_path(self, name: str) -> Path | None:
        if not name or name != Path(name).name:
            return None
        path = self.capture_dir / name
        try:
            resolved_dir = self.capture_dir.resolve()
            resolved_path = path.resolve()
        except OSError:
            return None
        if resolved_path.parent != resolved_dir:
            return None
        if not resolved_path.is_file() or resolved_path.suffix.lower() not in CAPTURE_EXTENSIONS:
            return None
        return resolved_path

    def thumbnail_path(self, name: str) -> Path | None:
        capture = self.capture_path(name)
        if capture is None:
            return None
        thumbnail = self._thumbnail_path_for_capture(capture)
        if not thumbnail.is_file():
            return None
        return thumbnail

    def generate_thumbnails_for_prefix(self, prefix: str | None, ffmpeg_bin: str = "ffmpeg") -> list[Path]:
        if not prefix:
            return []
        generated: list[Path] = []
        for path in sorted(self.capture_dir.glob(f"{prefix}*")):
            if not path.is_file() or path.suffix.lower() not in CAPTURE_EXTENSIONS:
                continue
            thumbnail = self.generate_thumbnail(path, ffmpeg_bin=ffmpeg_bin)
            if thumbnail is not None:
                generated.append(thumbnail)
        return generated

    def generate_thumbnail(self, capture_path: Path, ffmpeg_bin: str = "ffmpeg") -> Path | None:
        if not capture_path.is_file() or capture_path.suffix.lower() not in CAPTURE_EXTENSIONS:
            return None
        thumbnail_path = self._thumbnail_path_for_capture(capture_path)
        if thumbnail_path.exists() and thumbnail_path.stat().st_size > 0:
            return thumbnail_path

        tmp_path = thumbnail_path.with_name(f"{thumbnail_path.stem}.tmp{thumbnail_path.suffix}")
        for seek in ("00:00:05", "00:00:00.5", "00:00:00"):
            try:
                result = subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        seek,
                        "-i",
                        str(capture_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=320:-1",
                        str(tmp_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
            except (OSError, subprocess.TimeoutExpired):
                tmp_path.unlink(missing_ok=True)
                return None
            if result.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
                tmp_path.replace(thumbnail_path)
                return thumbnail_path
            tmp_path.unlink(missing_ok=True)
        return None

    def _thumbnail_path_for_capture(self, capture_path: Path) -> Path:
        return capture_path.with_suffix(THUMBNAIL_EXTENSION)
