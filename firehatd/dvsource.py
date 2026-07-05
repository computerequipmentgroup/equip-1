from __future__ import annotations

import asyncio
import os
from pathlib import Path


class DvSource:
    """A single dvgrab claim on the FireWire DV bus, tapped once and fanned out.

    One long-lived ``dvgrab -format raw -`` streams raw DV to stdout. The read
    loop delivers every chunk to:

      * any number of preview subscribers (bounded queues -> ffmpeg -> MJPEG), and
      * the active recording file, when a recording is running.

    Because the bus is claimed exactly once regardless of how many viewers are
    watching or whether a recording is running, preview and recording never
    contend for the FireWire bus. Recording start/stop just attaches/detaches a
    file to the shared stream -- no second dvgrab, no bus handoff.
    """

    def __init__(self, dvgrab_bin: str = "dvgrab", read_size: int = 256 * 1024):
        self.dvgrab_bin = dvgrab_bin
        self.read_size = read_size
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._record_fh = None
        self._record_aligned = False
        self._recording = False
        self._error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def recording(self) -> bool:
        return self._recording

    async def add_subscriber(self, maxsize: int = 8) -> asyncio.Queue:
        """Register a preview consumer and make sure dvgrab is running."""
        async with self._lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
            self._subscribers.add(queue)
            await self._ensure_running()
            return queue

    async def remove_subscriber(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)
            await self._maybe_stop()

    async def start_record(self, path: Path) -> None:
        """Begin persisting the shared DV stream to ``path``."""
        async with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._record_fh = open(path, "wb", buffering=1024 * 1024)
            self._record_aligned = False
            self._recording = True
            self._error = None
            await self._ensure_running()

    async def stop_record(self) -> None:
        async with self._lock:
            self._recording = False
            fh = self._record_fh
            self._record_fh = None
            if fh is not None:
                try:
                    fh.flush()
                    os.fsync(fh.fileno())
                except OSError:
                    pass
                fh.close()
            await self._maybe_stop()

    def take_error(self) -> str | None:
        """Return and clear the last stream error (one-shot)."""
        error = self._error
        self._error = None
        return error

    async def stop(self) -> None:
        async with self._lock:
            self._recording = False
            if self._record_fh is not None:
                try:
                    self._record_fh.close()
                except OSError:
                    pass
                self._record_fh = None
            await self._stop_proc()

    async def _ensure_running(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        self._proc = await asyncio.create_subprocess_exec(
            self.dvgrab_bin,
            "-buffers",
            "50",
            "-format",
            "raw",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader = asyncio.create_task(self._read_loop(self._proc))

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        stdout = proc.stdout
        assert stdout is not None
        try:
            while True:
                chunk = await stdout.read(self.read_size)
                if not chunk:
                    break
                if self._record_fh is not None:
                    self._write_record(chunk)
                for queue in list(self._subscribers):
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        queue.put_nowait(chunk)
                    except asyncio.QueueFull:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the daemon alive; surface via take_error
            self._error = f"dv source read error: {exc}"
        finally:
            # Signal every subscriber that the stream ended.
            for queue in list(self._subscribers):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            # dvgrab exiting while a file is still attached means the recording
            # ended unexpectedly (e.g. camera unplugged). Flush what we have and
            # flag it so the daemon can report the failure.
            if self._record_fh is not None:
                try:
                    self._record_fh.flush()
                    self._record_fh.close()
                except OSError:
                    pass
                self._record_fh = None
                self._recording = False
                if self._error is None:
                    self._error = "dvgrab stream ended while recording"

    def _write_record(self, chunk: bytes) -> None:
        if not self._record_aligned:
            # Best-effort: begin the file on a DV frame header so the capture
            # opens cleanly. If the marker isn't in this chunk, start anyway --
            # ffmpeg/players resync at the next frame boundary regardless.
            idx = chunk.find(b"\x1f\x07\x00")
            if idx > 0:
                chunk = chunk[idx:]
            self._record_aligned = True
        self._record_fh.write(chunk)

    async def _maybe_stop(self) -> None:
        if self._subscribers or self._recording:
            return
        await self._stop_proc()

    async def _stop_proc(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
