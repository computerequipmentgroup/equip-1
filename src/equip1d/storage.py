from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Callable


@dataclass(frozen=True)
class MountInfo:
    source: str
    mount_point: str
    filesystem_type: str


DV_BYTES_PER_MINUTE = 216 * 1024 * 1024
CAPTURE_EXTENSIONS = {".dv", ".dif", ".m2t", ".mts", ".ts", ".avi", ".mov", ".mp4", ".mkv"}
THUMBNAIL_EXTENSION = ".jpg"


@dataclass(frozen=True)
class StorageSnapshot:
    capture_dir: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    recording_minutes_available: int
    device: str | None = None
    device_kind: str = "unknown"
    mount_point: str | None = None
    filesystem_type: str | None = None


class StorageManager:
    def __init__(self, capture_dir: str | os.PathLike[str]):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> StorageSnapshot:
        mount = self._mount_for_capture_dir()
        if self._mount_source_missing(mount):
            # Avoid statvfs on a stale USB mount; it may fail or block after the
            # underlying /dev/sd* node disappeared.
            return self._unavailable_snapshot(mount)

        try:
            total, used, free = shutil.disk_usage(self.capture_dir)
        except OSError:
            # If USB storage is pulled without an explicit switch/unmount, /data
            # can remain as a stale mount and statvfs may fail. Keep the API/OLED
            # alive and report the mounted device as unavailable instead of
            # letting state generation crash.
            return self._unavailable_snapshot(mount)

        return StorageSnapshot(
            capture_dir=str(self.capture_dir),
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            recording_minutes_available=int(free / DV_BYTES_PER_MINUTE),
            device=mount.source if mount else None,
            device_kind=self._device_kind(mount),
            mount_point=mount.mount_point if mount else None,
            filesystem_type=mount.filesystem_type if mount else None,
        )

    def _unavailable_snapshot(self, mount: MountInfo | None) -> StorageSnapshot:
        return StorageSnapshot(
            capture_dir=str(self.capture_dir),
            total_bytes=0,
            used_bytes=0,
            free_bytes=0,
            recording_minutes_available=0,
            device=mount.source if mount else None,
            device_kind=self._device_kind(mount),
            mount_point=mount.mount_point if mount else None,
            filesystem_type=mount.filesystem_type if mount else None,
        )

    def _mount_for_capture_dir(self) -> MountInfo | None:
        try:
            capture_dir = self.capture_dir.resolve()
        except OSError:
            capture_dir = self.capture_dir.absolute()

        best: MountInfo | None = None
        for mount in self._read_mounts():
            mount_path = Path(mount.mount_point)
            try:
                capture_dir.relative_to(mount_path)
            except ValueError:
                continue
            if best is None or len(mount.mount_point) > len(best.mount_point):
                best = mount
        return best

    @staticmethod
    def _read_mounts() -> list[MountInfo]:
        mounts: list[MountInfo] = []
        try:
            lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
        except OSError:
            return mounts

        for line in lines:
            fields = line.split()
            if len(fields) < 3:
                continue
            mounts.append(
                MountInfo(
                    source=StorageManager._decode_mount_field(fields[0]),
                    mount_point=StorageManager._decode_mount_field(fields[1]),
                    filesystem_type=fields[2],
                )
            )
        return mounts

    @staticmethod
    def _decode_mount_field(value: str) -> str:
        return value.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")

    @staticmethod
    def _mount_source_missing(mount: MountInfo | None) -> bool:
        return mount is not None and mount.source.startswith("/dev/sd") and not Path(mount.source).exists()

    @staticmethod
    def _device_kind(mount: MountInfo | None) -> str:
        if mount is None:
            return "unknown"
        source = mount.source
        if source.startswith("/dev/mmcblk"):
            return "sd"
        if source.startswith("/dev/sd"):
            return "usb"
        if source.startswith("/dev/nvme"):
            return "nvme"
        if source in {"rootfs", "/dev/root"} or mount.mount_point == "/":
            return "rootfs"
        return "unknown"

    def has_recording_space(self, minimum_minutes: int = 1) -> bool:
        return self.snapshot().recording_minutes_available >= minimum_minutes

    def list_captures(self) -> list[dict]:
        captures: list[dict] = []
        entries: list[tuple[Path, os.stat_result]] = []
        try:
            for path in self.capture_dir.iterdir():
                try:
                    file_stat = path.stat()
                except OSError:
                    continue
                if not S_ISREG(file_stat.st_mode) or path.suffix.lower() not in CAPTURE_EXTENSIONS:
                    continue
                entries.append((path, file_stat))
        except OSError:
            return captures

        for path, file_stat in sorted(entries, key=lambda item: item[1].st_mtime, reverse=True):
            thumbnail_path = self._thumbnail_path_for_capture(path)
            capture = {
                "name": path.name,
                "path": str(path),
                "size_bytes": file_stat.st_size,
                "modified_at": file_stat.st_mtime,
                "download_url": f"/api/captures/{path.name}/download",
            }
            try:
                thumbnail_exists = thumbnail_path.exists()
            except OSError:
                thumbnail_exists = False
            if thumbnail_exists:
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

    def convert_capture_to_mp4(
        self,
        capture_path: Path,
        ffmpeg_bin: str = "ffmpeg",
        quality: str = "high",
        progress_callback: Callable[[int], None] | None = None,
        deinterlace: bool = True,
    ) -> Path | None:
        if not capture_path.is_file() or capture_path.suffix.lower() not in CAPTURE_EXTENSIONS:
            return None
        if capture_path.suffix.lower() == ".mp4":
            return capture_path

        target_path = capture_path.with_suffix(".mp4")
        if target_path.exists() and target_path.stat().st_size > 0:
            if progress_callback is not None:
                progress_callback(100)
            return target_path

        tmp_path = target_path.with_name(f"{target_path.stem}.tmp{target_path.suffix}")
        tmp_path.unlink(missing_ok=True)
        presets = {
            "small": {"crf": "28", "qv": "7", "audio": ["-c:a", "aac", "-b:a", "128k"]},
            "balanced": {"crf": "23", "qv": "5", "audio": ["-c:a", "aac", "-b:a", "128k"]},
            "high": {"crf": "18", "qv": "3", "audio": ["-c:a", "aac", "-b:a", "128k"]},
            "max": {"crf": "14", "qv": "1", "audio": ["-c:a", "aac", "-b:a", "192k"]},
        }
        quality_name = str(quality).lower()
        preset = presets.get(quality_name, presets["high"])
        video_filters = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        if deinterlace:
            video_filters.insert(0, "yadif=mode=send_frame:parity=auto:deint=all")
        video_filter = ",".join(video_filters)
        command_variants = [
            [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(capture_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                video_filter,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                preset["crf"],
                "-pix_fmt",
                "yuv420p",
                *preset["audio"],
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(tmp_path),
            ],
            [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(capture_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                video_filter,
                "-c:v",
                "mpeg4",
                "-q:v",
                preset["qv"],
                "-pix_fmt",
                "yuv420p",
                *preset["audio"],
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(tmp_path),
            ],
        ]

        duration_seconds = self._estimate_capture_duration_seconds(capture_path)
        last_error = "ffmpeg conversion failed"
        if progress_callback is not None:
            progress_callback(0)
        for command in command_variants:
            try:
                return_code, output = self._run_ffmpeg_progress(command, duration_seconds, progress_callback)
            except OSError as exc:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(str(exc)) from exc
            if return_code == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
                if progress_callback is not None:
                    progress_callback(100)
                tmp_path.replace(target_path)
                return target_path
            last_error = output.strip() or last_error
            tmp_path.unlink(missing_ok=True)
        raise RuntimeError(last_error)

    @staticmethod
    def _estimate_capture_duration_seconds(capture_path: Path) -> float:
        try:
            size_bytes = capture_path.stat().st_size
        except OSError:
            return 0.0
        return max(1.0, size_bytes / (DV_BYTES_PER_MINUTE / 60.0))

    @staticmethod
    def _run_ffmpeg_progress(
        command: list[str],
        duration_seconds: float,
        progress_callback: Callable[[int], None] | None,
    ) -> tuple[int, str]:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        last_percent = -1
        stdout_lines: list[str] = []
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                stdout_lines.append(line)
                seconds = StorageManager._progress_seconds(line)
                if seconds is None or duration_seconds <= 0:
                    continue
                percent = max(0, min(99, int((seconds / duration_seconds) * 100)))
                if progress_callback is not None and percent != last_percent:
                    last_percent = percent
                    progress_callback(percent)
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        return proc.wait(), "\n".join(part for part in [stderr, "\n".join(stdout_lines)] if part)

    @staticmethod
    def _progress_seconds(line: str) -> float | None:
        key, sep, value = line.partition("=")
        if not sep:
            return None
        if key in {"out_time_us", "out_time_ms"}:
            try:
                return int(value) / 1_000_000.0
            except ValueError:
                return None
        if key != "out_time":
            return None
        try:
            hours, minutes, seconds = value.split(":")
            return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)
        except (ValueError, TypeError):
            return None

    def _thumbnail_path_for_capture(self, capture_path: Path) -> Path:
        return capture_path.with_suffix(THUMBNAIL_EXTENSION)
