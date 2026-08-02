from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import AsyncIterator

from .dvsource import DvSource, STREAM_FORMAT_HDV
from .logging import debug_enabled, log, should_log
from .settings import Equip1Settings


class PreviewBusyError(RuntimeError):
    pass


class PreviewSourceError(RuntimeError):
    pass


class MjpegPreview:
    """On-demand DV/HDV streaming to browsers and network players.

    The browser preview is served as MJPEG; VLC and other network players are
    served as remuxed Matroska (the native DV or HDV stream copied into an MKV
    container, no transcode). Both flavours subscribe to the single shared
    FireWire source (``DvSource``) and share a busy-lock, so only one consumer is
    ever active at a time and preview never contends with the recorder for the
    device.
    """

    boundary = "equip1frame"

    def __init__(self, source: DvSource, ffmpeg_bin: str = "ffmpeg", settings: Equip1Settings | None = None):
        self.source = source
        self.ffmpeg_bin = ffmpeg_bin
        settings = settings or Equip1Settings()
        # Idle preview defaults aim for VLC-like fidelity: full-rate, full-size
        # MJPEG off the shared DV/HDV source. Every value stays env-overridable so
        # the feed can be dialed back on the device if CPU/bandwidth demands it.
        self.fps = settings.get("preview", "fps", "25", env="EQUIP1_PREVIEW_FPS") or "25"
        self.size = settings.get("preview", "size", "720:540", env="EQUIP1_PREVIEW_SIZE") or "720:540"
        # Recording preview stays modest -- the recorder is writing the capture
        # to disk at the same time, so the browser feed yields CPU to it.
        self.recording_fps = settings.get(
            "preview", "recording_fps", "2", env="EQUIP1_PREVIEW_RECORDING_FPS"
        ) or "2"
        self.recording_size = settings.get(
            "preview", "recording_size", "480:360", env="EQUIP1_PREVIEW_RECORDING_SIZE"
        ) or "480:360"
        default_filter = (
            f"fps={self.fps},scale={self.size}:force_original_aspect_ratio=increase,"
            f"crop={self.size},setsar=1"
        )
        default_recording_filter = (
            f"fps={self.recording_fps},scale={self.recording_size}:"
            f"force_original_aspect_ratio=increase,crop={self.recording_size},setsar=1"
        )
        self.video_filter = (
            settings.get("preview", "filter", default_filter, env="EQUIP1_PREVIEW_FILTER") or default_filter
        )
        self.recording_video_filter = (
            settings.get(
                "preview", "recording_filter", default_recording_filter, env="EQUIP1_PREVIEW_RECORDING_FILTER"
            )
            or default_recording_filter
        )
        self.quality = settings.get("preview", "quality", "4", env="EQUIP1_PREVIEW_QUALITY") or "4"
        self.recording_quality = settings.get(
            "preview", "recording_quality", "5", env="EQUIP1_PREVIEW_RECORDING_QUALITY"
        ) or "5"
        self._active = False
        self._active_since: float | None = None
        self._process: asyncio.subprocess.Process | None = None

    @property
    def media_type(self) -> str:
        return f"multipart/x-mixed-replace; boundary={self.boundary}"

    @property
    def mkv_media_type(self) -> str:
        return "video/x-matroska"

    @property
    def active(self) -> bool:
        return self._active

    @property
    def active_seconds(self) -> float:
        if not self._active or self._active_since is None:
            return 0.0
        return max(0.0, time.monotonic() - self._active_since)

    def stream(self, recording: bool = False) -> AsyncIterator[bytes]:
        return self._begin(mkv=False, recording=recording)

    def stream_mkv(self, recording: bool = False) -> AsyncIterator[bytes]:
        return self._begin(mkv=True, recording=recording)

    def _begin(self, mkv: bool, recording: bool) -> AsyncIterator[bytes]:
        if self._active:
            raise PreviewBusyError("Preview is already active")
        self._active = True
        self._active_since = time.monotonic()
        return self._stream(mkv=mkv, recording=recording)

    async def stop(self) -> None:
        await self._stop_process(self._process)
        self._process = None
        self._active = False
        self._active_since = None

    async def _stream(self, mkv: bool, recording: bool) -> AsyncIterator[bytes]:
        subscription = self.source.subscribe()
        ffmpeg_proc: asyncio.subprocess.Process | None = None
        tasks: list[asyncio.Task] = []
        frames = 0
        label = "MKV stream" if mkv else "preview"
        unit = "chunk" if mkv else "frame"
        try:
            stream_format = await self.source.wait_for_stream_format(timeout=2.0)
            self._log(
                f"starting {label} from shared {stream_format.upper()} source recording={recording}",
                always=True,
            )
            ffmpeg_proc = await asyncio.create_subprocess_exec(
                *self._ffmpeg_stdin_command(recording=recording, mkv=mkv, stream_format=stream_format),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._process = ffmpeg_proc
            if ffmpeg_proc.stderr is not None:
                tasks.append(asyncio.create_task(self._drain_stderr("ffmpeg", ffmpeg_proc.stderr, always=True)))
            if ffmpeg_proc.stdin is not None:
                tasks.append(asyncio.create_task(self._pump_subscription(subscription, ffmpeg_proc.stdin)))
            if ffmpeg_proc.stdout is None:
                return
            async for payload in self._emit(ffmpeg_proc.stdout, mkv):
                frames += 1
                if frames == 1:
                    self._log(f"{label} emitted first {unit}", always=True)
                yield payload
        finally:
            subscription.close()
            for task in tasks:
                task.cancel()
            await self._stop_process(ffmpeg_proc)
            if self._process is ffmpeg_proc:
                self._process = None
            self._active = False
            self._active_since = None
            ffmpeg_rc = ffmpeg_proc.returncode if ffmpeg_proc is not None else "n/a"
            self._log(f"{label} stopped {unit}s={frames} ffmpeg_rc={ffmpeg_rc}", always=True)

    def _emit(self, stream: asyncio.StreamReader, mkv: bool) -> AsyncIterator[bytes]:
        if mkv:
            return self._raw_chunks(stream)
        return self._multipart_mjpeg(stream)

    async def _raw_chunks(self, stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                return
            yield chunk

    async def _multipart_mjpeg(self, stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
        async for frame in self._jpeg_frames(stream):
            yield self._multipart_frame(frame)

    def _ffmpeg_stdin_command(
        self,
        recording: bool = False,
        mkv: bool = False,
        stream_format: str | None = None,
    ) -> list[str]:
        # The shared source is inherently real-time, so no "-re" pacing is
        # needed on the input.
        stream_format = stream_format or self.source.stream_format
        input_format = "mpegts" if stream_format == STREAM_FORMAT_HDV else "dv"
        command = [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", input_format, "-i", "pipe:0"]
        if mkv:
            # Copy the native DV/HDV stream straight into a live Matroska
            # container (no transcode) -- cheap on the RK3528 and played natively by VLC.
            command.extend(["-c", "copy", "-f", "matroska", "pipe:1"])
        else:
            command.extend(self._output_args(recording=recording))
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

    async def _pump_subscription(self, subscription, writer: asyncio.StreamWriter) -> None:
        try:
            async for chunk in subscription:
                writer.write(chunk)
                try:
                    await writer.drain()
                except (BrokenPipeError, ConnectionResetError):
                    return
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

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
        preview_debug = os.environ.get("EQUIP1_PREVIEW_DEBUG") == "1"
        if preview_debug or debug_enabled() or (always and should_log("info")):
            try:
                log_path = os.environ.get("EQUIP1_PREVIEW_DEBUG_LOG", "/var/log/equip1/preview-debug.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{message}\n")
            except OSError:
                pass
        if preview_debug or debug_enabled():
            log(f"preview: {message}", level="debug")
