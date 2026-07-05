from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import AsyncIterator
from pathlib import Path


class PreviewBusyError(RuntimeError):
    pass


class PreviewSourceError(RuntimeError):
    pass


class MjpegPreview:
    """On-demand DV preview as browser-compatible MJPEG.

    Idle preview uses dvgrab as the FireWire reader and pipes raw DV into
    ffmpeg. Recording preview follows the growing capture file and feeds it to
    ffmpeg through stdin, so dvgrab remains the only FireWire reader/writer.
    """

    boundary = "firehatframe"

    def __init__(self, ffmpeg_bin: str = "ffmpeg", dvgrab_bin: str = "dvgrab"):
        self.ffmpeg_bin = ffmpeg_bin
        self.dvgrab_bin = dvgrab_bin
        self.fps = os.environ.get("FIREHAT_PREVIEW_FPS", "6")
        self.size = os.environ.get("FIREHAT_PREVIEW_SIZE", "320:240")
        self.recording_fps = os.environ.get("FIREHAT_PREVIEW_RECORDING_FPS", "2")
        self.recording_size = os.environ.get("FIREHAT_PREVIEW_RECORDING_SIZE", "480:360")
        self.video_filter = os.environ.get(
            "FIREHAT_PREVIEW_FILTER",
            f"fps={self.fps},scale={self.size}:force_original_aspect_ratio=increase,crop={self.size},setsar=1",
        )
        self.recording_video_filter = os.environ.get(
            "FIREHAT_PREVIEW_RECORDING_FILTER",
            f"fps={self.recording_fps},scale={self.recording_size}:force_original_aspect_ratio=increase,crop={self.recording_size},setsar=1",
        )
        self.quality = os.environ.get("FIREHAT_PREVIEW_QUALITY", "8")
        self.recording_quality = os.environ.get("FIREHAT_PREVIEW_RECORDING_QUALITY", "5")
        self.recording_lag_bytes = int(os.environ.get("FIREHAT_PREVIEW_RECORDING_LAG_BYTES", "60000000"))
        self._active = False
        self._active_since: float | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._source_process: asyncio.subprocess.Process | None = None

    @property
    def media_type(self) -> str:
        return f"multipart/x-mixed-replace; boundary={self.boundary}"

    @property
    def active(self) -> bool:
        return self._active

    @property
    def active_seconds(self) -> float:
        if not self._active or self._active_since is None:
            return 0.0
        return max(0.0, time.monotonic() - self._active_since)

    def stream(self) -> AsyncIterator[bytes]:
        if self._active:
            raise PreviewBusyError("Preview is already active")
        self._active = True
        self._active_since = time.monotonic()
        return self._stream_dvgrab_claimed()

    def stream_recording(self, capture_dir: Path, prefix: str) -> AsyncIterator[bytes]:
        if self._active:
            raise PreviewBusyError("Preview is already active")
        self._active = True
        self._active_since = time.monotonic()
        return self._stream_recording_claimed(capture_dir, prefix)

    async def stop(self) -> None:
        await asyncio.gather(
            self._stop_process(self._source_process),
            self._stop_process(self._process),
            return_exceptions=True,
        )
        self._source_process = None
        self._process = None
        self._active = False
        self._active_since = None

    async def _stream_dvgrab_claimed(self) -> AsyncIterator[bytes]:
        dvgrab_proc: asyncio.subprocess.Process | None = None
        ffmpeg_proc: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task] = []
        frames = 0
        try:
            self._log("starting idle preview via dvgrab stdout", always=True)
            dvgrab_proc = await asyncio.create_subprocess_exec(
                self.dvgrab_bin,
                "-buffers",
                "20",
                "-format",
                "raw",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._source_process = dvgrab_proc
            ffmpeg_proc = await asyncio.create_subprocess_exec(
                *self._ffmpeg_stdin_command(realtime=False),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._process = ffmpeg_proc
            if dvgrab_proc.stderr is not None:
                tasks.append(asyncio.create_task(self._drain_stderr("dvgrab", dvgrab_proc.stderr, always=True)))
            if ffmpeg_proc.stderr is not None:
                tasks.append(asyncio.create_task(self._drain_stderr("ffmpeg", ffmpeg_proc.stderr, always=True)))
            if dvgrab_proc.stdout is not None and ffmpeg_proc.stdin is not None:
                tasks.append(asyncio.create_task(self._pump_stream(dvgrab_proc.stdout, ffmpeg_proc.stdin)))
            if ffmpeg_proc.stdout is None:
                return
            async for frame in self._jpeg_frames(ffmpeg_proc.stdout):
                frames += 1
                if frames == 1:
                    self._log("idle preview emitted first frame", always=True)
                yield self._multipart_frame(frame)
        finally:
            for task in tasks:
                task.cancel()
            await self._stop_process(dvgrab_proc)
            await self._stop_process(ffmpeg_proc)
            if self._source_process is dvgrab_proc:
                self._source_process = None
            if self._process is ffmpeg_proc:
                self._process = None
            self._active = False
            self._active_since = None
            dvgrab_rc = dvgrab_proc.returncode if dvgrab_proc is not None else "n/a"
            ffmpeg_rc = ffmpeg_proc.returncode if ffmpeg_proc is not None else "n/a"
            self._log(f"idle preview stopped frames={frames} dvgrab_rc={dvgrab_rc} ffmpeg_rc={ffmpeg_rc}", always=True)

    async def _stream_recording_claimed(self, capture_dir: Path, prefix: str) -> AsyncIterator[bytes]:
        proc: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task] = []
        frames = 0
        try:
            path = await self._wait_for_recording_file(capture_dir, prefix)
            self._log(f"starting recording preview from {path.name}", always=True)
            proc = await asyncio.create_subprocess_exec(
                *self._ffmpeg_stdin_command(realtime=True, recording=True),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._process = proc
            if proc.stderr is not None:
                tasks.append(asyncio.create_task(self._drain_stderr("ffmpeg", proc.stderr, always=True)))
            if proc.stdin is not None:
                tasks.append(asyncio.create_task(self._pump_growing_file(path, proc.stdin)))
            if proc.stdout is None:
                return
            async for frame in self._jpeg_frames(proc.stdout):
                frames += 1
                if frames == 1:
                    self._log("recording preview emitted first frame", always=True)
                yield self._multipart_frame(frame)
        finally:
            for task in tasks:
                task.cancel()
            await self._stop_process(proc)
            if self._process is proc:
                self._process = None
            self._active = False
            self._active_since = None
            ffmpeg_rc = proc.returncode if proc is not None else "n/a"
            self._log(f"recording preview stopped frames={frames} ffmpeg_rc={ffmpeg_rc}", always=True)

    def _ffmpeg_stdin_command(self, realtime: bool, recording: bool = False) -> list[str]:
        command = [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error"]
        if realtime:
            command.append("-re")
        command.extend(["-f", "dv", "-i", "pipe:0", *self._output_args(recording=recording)])
        return command

    def _output_args(self, recording: bool = False) -> list[str]:
        return [
            "-an",
            "-vf",
            self.recording_video_filter if recording else self.video_filter,
            "-q:v",
            self.recording_quality if recording else self.quality,
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]

    async def _wait_for_recording_file(self, capture_dir: Path, prefix: str) -> Path:
        for _ in range(100):
            matches = [
                path
                for path in sorted(capture_dir.glob(f"{prefix}*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if path.is_file() and path.suffix.lower() in {".dv", ".avi", ".mov", ".mp4", ".mkv"}
            ]
            if matches:
                return matches[0]
            await asyncio.sleep(0.1)
        raise PreviewSourceError("Recording file is not ready")

    async def _pump_stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            chunk = await reader.read(64 * 1024)
            if not chunk:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                return
            writer.write(chunk)
            try:
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                return

    async def _pump_growing_file(self, path: Path, writer: asyncio.StreamWriter) -> None:
        with path.open("rb") as handle:
            try:
                size = path.stat().st_size
                if size > self.recording_lag_bytes:
                    handle.seek(max(0, size - self.recording_lag_bytes))
            except OSError:
                pass
            while True:
                chunk = await asyncio.to_thread(handle.read, 64 * 1024)
                if chunk:
                    writer.write(chunk)
                    try:
                        await writer.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                else:
                    await asyncio.sleep(0.1)

    async def _jpeg_frames(self, stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
        buffer = bytearray()
        soi = b"\xff\xd8"
        eoi = b"\xff\xd9"
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            buffer.extend(chunk)
            while True:
                start = buffer.find(soi)
                if start < 0:
                    if len(buffer) > 1:
                        del buffer[:-1]
                    break
                end = buffer.find(eoi, start + 2)
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    break
                end += 2
                frame = bytes(buffer[start:end])
                del buffer[:end]
                yield frame

    def _multipart_frame(self, frame: bytes) -> bytes:
        header = (
            f"--{self.boundary}\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame)}\r\n"
            "Cache-Control: no-store\r\n"
            "\r\n"
        ).encode("ascii")
        return header + frame + b"\r\n"

    async def _stop_process(self, proc: asyncio.subprocess.Process | None) -> None:
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.5)
            return
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            self._log(f"preview process {proc.pid} did not exit after SIGKILL; abandoning handle", always=True)

    async def _drain_stderr(self, label: str, stream: asyncio.StreamReader, always: bool = False) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            self._log(f"{label}: {line.decode(errors='replace').rstrip()}", always=always)

    def _log(self, message: str, always: bool = False) -> None:
        if always or os.environ.get("FIREHAT_PREVIEW_DEBUG") == "1" or Path("/data/.firehat-debug").exists():
            try:
                with open("/data/preview-debug.log", "a", encoding="utf-8") as handle:
                    handle.write(f"{message}\n")
            except OSError:
                pass
        if os.environ.get("FIREHAT_PREVIEW_DEBUG") == "1":
            print(f"preview: {message}", flush=True)
