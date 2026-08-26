from __future__ import annotations

import asyncio
import fcntl
import os
import queue
import signal
import subprocess
import threading
import time

from .dvmetadata import DvRecordingDateScanner, DvTimecodeScanner
from .logging import debug_enabled, log, should_log


StreamFormat = str
STREAM_FORMAT_DV: StreamFormat = "dv"
STREAM_FORMAT_HDV: StreamFormat = "hdv"
STREAM_FORMAT_UNKNOWN: StreamFormat = "unknown"


class DvSubscription:
    """A single preview consumer of the shared DV/HDV stream.

    Chunks are delivered through a bounded queue with drop-oldest semantics, so
    a slow or stalled preview can never apply backpressure to the source read
    loop (and therefore can never threaten the recording write path).
    """

    def __init__(self, source: "DvSource", maxsize: int):
        self._source = source
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    def offer(self, chunk: bytes | None) -> None:
        try:
            self.queue.put_nowait(chunk)
        except asyncio.QueueFull:
            # Drop the oldest chunk to make room; preview may glitch, recording
            # never does.
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

    async def __aiter__(self):
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                return
            yield chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._source._remove_subscriber(self)


class DvSource:
    """The single long-lived FireWire DV/HDV reader.

    One ``dvgrab -format raw -`` process owns the FireWire claim for as long as
    a camera is connected. dvgrab auto-switches to MPEG-2 TS output when AV/C
    identifies an HDV source, so the first bytes from stdout are classified as
    raw DV or native HDV/MPEG-TS. A cheap read loop moves those bytes to two
    kinds of consumers:

    * the recording sink -- an open file written on a dedicated thread, toggled
      on/off instantly (this is the priority path);
    * any number of preview subscribers -- bounded, drop-oldest queues.

    Because the stream is always flowing, starting a recording is just "open a
    file on the bytes already arriving", so there is no device hand-off and no
    startup latency.
    """

    def __init__(self, dvgrab_bin: str = "dvgrab", read_size: int = 128 * 1024):
        self.dvgrab_bin = dvgrab_bin
        self._read_size = read_size
        # dvgrab's internal frame ring; the shared source drains it on a dedicated
        # OS thread, but generous buffering still absorbs any drain hiccup so the
        # FireWire capture never underruns.
        self._buffers = os.environ.get("EQUIP1_DV_BUFFERS", "50")
        # Target kernel pipe size between dvgrab and our reader (bytes). Non-root
        # is capped at /proc/sys/fs/pipe-max-size, so we degrade gracefully.
        self._pipe_size = int(os.environ.get("EQUIP1_DV_PIPE_BYTES", str(1024 * 1024)))
        self._proc: asyncio.subprocess.Process | None = None
        # The pipe is drained by a blocking thread (not the event loop) so preview
        # transcoding / websocket / HTTP load can never delay reads and starve the
        # recording. Preview fan-out is marshalled back onto the loop.
        self._reader_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stderr_task: asyncio.Task | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._stopping = False
        self._subscribers: list[DvSubscription] = []
        self._preview_maxsize = int(os.environ.get("EQUIP1_DV_PREVIEW_QUEUE", "32"))

        # Some camcorders emit otherwise-valid DV DIF blocks with a sequence
        # nibble that libavformat rejects as "Cannot find DV header". Normalise
        # only the DIF block ID byte at each 80-byte block boundary. Known-good
        # streams are unchanged; set EQUIP1_DV_NORMALIZE_DIF=0 to disable.
        normalize_setting = os.environ.get("EQUIP1_DV_NORMALIZE_DIF", "1").strip().lower()
        self._normalize_dif_headers = normalize_setting not in {"0", "false", "no", "off"}
        self._dif_stream_offset = 0
        self._dif_normalized_blocks = 0
        self._dif_normalizer_logged = False

        # Recording sink. The reference is swapped atomically so the read loop
        # only ever sees a fully-initialised writer.
        self._rec_queue: queue.Queue[bytes | None] | None = None
        self._rec_thread: threading.Thread | None = None
        self._rec_handle = None
        self._rec_proc: subprocess.Popen | None = None
        self._rec_path: Path | None = None
        self._rec_maxsize = int(os.environ.get("EQUIP1_DV_RECORD_QUEUE", "2048"))
        self._rec_dropped = 0
        self.recording_error: str | None = None

        self._date_scanner = DvRecordingDateScanner()
        self._timecode_scanner = DvTimecodeScanner()
        self._latest_recording_datetime = None
        self._latest_timecode = None
        self._stream_format: StreamFormat = STREAM_FORMAT_UNKNOWN
        self._format_event: asyncio.Event | None = None

    # ---- lifecycle -----------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def recording(self) -> bool:
        return self._rec_queue is not None

    @property
    def latest_recording_datetime(self):
        return self._latest_recording_datetime

    @property
    def latest_timecode(self):
        return self._latest_timecode

    @property
    def stream_format(self) -> StreamFormat:
        return self._stream_format

    @property
    def capture_extension(self) -> str:
        return ".m2t" if self._stream_format == STREAM_FORMAT_HDV else ".dv"

    async def wait_for_stream_format(self, timeout: float = 2.0) -> StreamFormat:
        if self._stream_format != STREAM_FORMAT_UNKNOWN:
            return self._stream_format
        event = self._format_event
        if event is None:
            return STREAM_FORMAT_UNKNOWN
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return self._stream_format
        return self._stream_format

    async def ensure_running(self, want: bool) -> None:
        # Serialised so concurrent callers (monitor loop, record start, stream
        # start) can never spawn two dvgrab processes for the one device.
        async with self._lifecycle_lock:
            if want:
                if not self.running:
                    await self._spawn()
            else:
                if self._proc is not None:
                    await self._stop_locked()

    async def _spawn(self) -> None:
        self._stopping = False
        self._loop = asyncio.get_running_loop()
        self._dif_stream_offset = 0
        self._dif_normalizer_logged = False
        self._date_scanner = DvRecordingDateScanner()
        self._timecode_scanner = DvTimecodeScanner()
        self._latest_recording_datetime = None
        self._latest_timecode = None
        self._stream_format = STREAM_FORMAT_UNKNOWN
        self._format_event = asyncio.Event()
        self._log("starting shared dvgrab DV/HDV source", always=True)
        # Give dvgrab a private pipe we own the read end of, so a blocking thread
        # can drain it independently of the event loop.
        read_fd, write_fd = os.pipe()
        self._set_pipe_size(read_fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.dvgrab_bin,
                "-buffers",
                self._buffers,
                "-format",
                "raw",
                "-",
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except BaseException:
            os.close(read_fd)  # don't leak the read end if the spawn failed
            raise
        finally:
            os.close(write_fd)  # parent keeps only the read end
        self._proc = proc
        thread = threading.Thread(
            target=self._reader_run, args=(read_fd, self._loop), name="dv-reader", daemon=True
        )
        self._reader_thread = thread
        thread.start()
        if proc.stderr is not None:
            self._stderr_task = asyncio.create_task(self._drain_stderr(proc.stderr))

    def _set_pipe_size(self, fd: int) -> None:
        setter = getattr(fcntl, "F_SETPIPE_SZ", None)
        if setter is None:  # not Linux (e.g. dev on macOS)
            return
        try:
            fcntl.fcntl(fd, setter, self._pipe_size)
        except OSError:
            # Non-root can't exceed pipe-max-size; the default 64 KiB still works,
            # it just gives dvgrab a bit less slack.
            pass

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        # Signals the reader thread's EOF handler that this is a clean teardown,
        # not an unexpected source loss, so it doesn't flag the recording failed.
        self._stopping = True
        stderr_task = self._stderr_task
        self._stderr_task = None
        if stderr_task is not None:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        # Kill dvgrab first: closing the write end makes the reader thread's
        # blocking os.read() return EOF so it can exit.
        await self._terminate_proc()
        thread = self._reader_thread
        self._reader_thread = None
        if thread is not None:
            # Off the event loop so a wedged dvgrab (rare uninterruptible-sleep
            # case) can't block the daemon; the daemon thread is then abandoned
            # and exits once dvgrab finally dies.
            await asyncio.to_thread(thread.join, 2.0)
        # A caller-initiated stop closes the recording sink cleanly without
        # flagging it as a failure. Clear live metadata so snapshots do not show
        # stale tape position while the DV/HDV source is stopped.
        self.stop_recording()
        self._latest_recording_datetime = None
        self._latest_timecode = None
        self._stream_format = STREAM_FORMAT_UNKNOWN
        if self._format_event is not None:
            self._format_event.set()
        self._close_all_subscribers()

    async def _terminate_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGINT)
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
            self._log(f"dvgrab source {proc.pid} did not exit after SIGKILL", always=True)

    # ---- reader thread -------------------------------------------------

    def _reader_run(self, read_fd: int, loop: asyncio.AbstractEventLoop) -> None:
        # Runs on a dedicated OS thread: a blocking read that keeps dvgrab's pipe
        # drained no matter how busy the event loop is. Recording goes to a
        # thread-safe queue here; preview fan-out is marshalled onto the loop.
        first = True
        try:
            while True:
                try:
                    chunk = os.read(read_fd, self._read_size)
                except OSError:
                    break
                if not chunk:
                    break
                chunk = self._prepare_chunk(chunk, loop)
                if first:
                    loop.call_soon_threadsafe(
                        self._log,
                        f"{self._stream_format.upper()} source emitted first bytes",
                        True,
                    )
                    first = False
                rec = self._rec_queue
                if rec is not None and self.recording_error is None:
                    # Recording is the priority path: never intentionally drop DV/HDV
                    # bytes. If storage stalls, let the larger recording queue and
                    # dvgrab's buffers absorb it instead of creating silent gaps in
                    # the capture file.
                    rec.put(chunk)
                if self._subscribers:
                    loop.call_soon_threadsafe(self._fanout, chunk)
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass
            loop.call_soon_threadsafe(self._on_reader_eof)

    def _prepare_chunk(self, chunk: bytes, loop: asyncio.AbstractEventLoop) -> bytes:
        if self._stream_format == STREAM_FORMAT_UNKNOWN:
            self._set_stream_format(self._detect_stream_format(chunk), loop)
        if self._stream_format == STREAM_FORMAT_HDV:
            return chunk

        chunk = self._normalize_dif_chunk(chunk)
        recorded_at = self._date_scanner.feed(chunk)
        if recorded_at is not None:
            self._latest_recording_datetime = recorded_at
        timecode = self._timecode_scanner.feed(chunk)
        if timecode is not None:
            self._latest_timecode = str(timecode)
        return chunk

    def _set_stream_format(self, stream_format: StreamFormat, loop: asyncio.AbstractEventLoop) -> None:
        if stream_format == STREAM_FORMAT_UNKNOWN or self._stream_format != STREAM_FORMAT_UNKNOWN:
            return
        self._stream_format = stream_format
        loop.call_soon_threadsafe(self._notify_stream_format, stream_format)

    def _notify_stream_format(self, stream_format: StreamFormat) -> None:
        self._log(f"detected {stream_format.upper()} stream", always=True)
        if self._format_event is not None:
            self._format_event.set()

    @staticmethod
    def _detect_stream_format(chunk: bytes) -> StreamFormat:
        # Native HDV is MPEG-2 transport stream: 188-byte packets with 0x47 sync.
        # Try every possible alignment because an os.read() may begin mid-packet.
        if len(chunk) >= 188 * 3:
            limit = min(188, len(chunk) - (188 * 3) + 1)
            for start in range(limit):
                packet_count = 0
                for offset in range(start, len(chunk), 188):
                    if chunk[offset] != 0x47:
                        break
                    packet_count += 1
                    if packet_count >= 3:
                        return STREAM_FORMAT_HDV
        # dvgrab stdout otherwise contains raw DV DIF frames. Defaulting to DV
        # preserves existing behaviour and lets the DV header normalizer run.
        return STREAM_FORMAT_DV

    def _normalize_dif_chunk(self, chunk: bytes) -> bytes:
        if not self._normalize_dif_headers or not chunk:
            return chunk

        data = bytearray(chunk)
        first_block = (80 - self._dif_stream_offset) % 80
        changed = 0
        for offset in range(first_block, len(data), 80):
            block_id = data[offset]
            section = block_id & 0xF0
            if section in (0x10, 0x30):
                normalized = section | 0x0F
            elif section in (0x50, 0x70, 0x90):
                normalized = section | 0x07
            else:
                continue
            if normalized != block_id:
                data[offset] = normalized
                changed += 1

        self._dif_stream_offset = (self._dif_stream_offset + len(chunk)) % 80
        if changed:
            self._dif_normalized_blocks += changed
            if not self._dif_normalizer_logged:
                self._dif_normalizer_logged = True
                self._log("normalizing non-standard DV DIF headers", always=True)
            return bytes(data)
        return chunk

    def _fanout(self, chunk: bytes) -> None:
        # Runs on the event loop, where the asyncio subscriber queues live.
        for sub in list(self._subscribers):
            sub.offer(chunk)

    def _on_reader_eof(self) -> None:
        if self._stopping:
            return
        # Source ended on its own (unplug / dvgrab crash) rather than via stop();
        # tear down consumers so they can reconnect and flag any live recording.
        if self.recording:
            self.recording_error = "DV/HDV source stopped while recording"
            self.stop_recording()
        self._latest_recording_datetime = None
        self._latest_timecode = None
        self._stream_format = STREAM_FORMAT_UNKNOWN
        if self._format_event is not None:
            self._format_event.set()
        self._close_all_subscribers()

    # ---- preview subscribers ------------------------------------------

    def subscribe(self) -> DvSubscription:
        sub = DvSubscription(self, self._preview_maxsize)
        self._subscribers.append(sub)
        return sub

    def _remove_subscriber(self, sub: DvSubscription) -> None:
        try:
            self._subscribers.remove(sub)
        except ValueError:
            pass

    def _close_all_subscribers(self) -> None:
        for sub in list(self._subscribers):
            sub.offer(None)
        self._subscribers.clear()

    # ---- recording sink ------------------------------------------------

    def start_recording(self, path: Path, ffmpeg_bin: str = "ffmpeg") -> None:
        """Open ``path`` and route the live DV/HDV stream into it. Fast + sync.

        Raw `.dv`/`.m2t` captures are written directly. `.mov` and `.avi` DV
        captures are stream-copied through ffmpeg into a container, preserving
        the original DV video/audio essence without transcoding.
        """
        if self.recording:
            raise RuntimeError("Already recording")
        self.recording_error = None
        self._rec_dropped = 0
        self._rec_path = path
        self._rec_proc = None
        self._rec_handle = self._open_recording_sink(path, ffmpeg_bin)
        rec_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=self._rec_maxsize)
        self._rec_thread = threading.Thread(
            target=self._recording_writer, args=(rec_queue, self._rec_handle), daemon=True
        )
        self._rec_thread.start()
        # Publish last so the read loop never sees a half-initialised sink.
        self._rec_queue = rec_queue

    def _open_recording_sink(self, path: Path, ffmpeg_bin: str):
        suffix = path.suffix.lower()
        if suffix not in {".mov", ".avi"}:
            return open(path, "wb", buffering=0)
        if self._stream_format == STREAM_FORMAT_HDV:
            raise RuntimeError(f"{suffix} recording is only available for DV streams")
        proc = subprocess.Popen(
            [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "dv",
                "-i",
                "pipe:0",
                "-map",
                "0",
                "-c",
                "copy",
                str(path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.stdin is None:
            proc.kill()
            raise RuntimeError("Could not open ffmpeg stdin for recording")
        self._rec_proc = proc
        return proc.stdin

    def stop_recording(self) -> None:
        rec_queue = self._rec_queue
        self._rec_queue = None
        if rec_queue is not None:
            rec_queue.put(None)  # sentinel: flush + exit writer thread
        thread = self._rec_thread
        self._rec_thread = None
        if thread is not None:
            thread.join(timeout=5.0)
        handle = self._rec_handle
        self._rec_handle = None
        proc = self._rec_proc
        self._rec_proc = None
        if handle is not None:
            try:
                handle.flush()
                if proc is None:
                    os.fsync(handle.fileno())
            except OSError:
                pass
            finally:
                handle.close()
        if proc is not None:
            try:
                return_code = proc.wait(timeout=30.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                return_code = proc.wait(timeout=5.0)
            if return_code != 0:
                self.recording_error = f"ffmpeg recording muxer exited with status {return_code}"
        if self._rec_dropped:
            self._log(f"recording dropped {self._rec_dropped} chunk(s) under disk stall", always=True)
        self._rec_path = None

    def _recording_writer(self, rec_queue: queue.Queue, handle) -> None:
        while True:
            item = rec_queue.get()
            if item is None:
                return
            try:
                handle.write(item)
            except OSError as exc:
                self.recording_error = f"recording write failed: {exc}"
                return

    # ---- logging -------------------------------------------------------

    def _log(self, message: str, always: bool = False) -> None:
        preview_debug = os.environ.get("EQUIP1_PREVIEW_DEBUG") == "1"
        if preview_debug or debug_enabled() or (always and should_log("info")):
            try:
                log_path = os.environ.get("EQUIP1_DVSOURCE_DEBUG_LOG", "/var/log/equip1/dvsource-debug.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{time.time():.3f} {message}\n")
            except OSError:
                pass
        if preview_debug or debug_enabled():
            log(f"dvsource: {message}", level="debug")

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await stream.readline()
            except Exception:
                return
            if not line:
                return
            self._log(f"dvgrab: {line.decode(errors='replace').rstrip()}", always=True)
