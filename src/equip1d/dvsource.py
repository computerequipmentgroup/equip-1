from __future__ import annotations

import asyncio
import fcntl
import os
import queue
import signal
import threading
import time

from .logging import debug_enabled, log, should_log


class DvSubscription:
    """A single preview consumer of the shared DV stream.

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
    """The single long-lived FireWire DV reader.

    One ``dvgrab -format raw -`` process owns the FireWire claim for as long as
    a camera is connected. A cheap read loop moves raw DV byte chunks to two
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
        self._rec_path: Path | None = None
        self._rec_maxsize = int(os.environ.get("EQUIP1_DV_RECORD_QUEUE", "2048"))
        self._rec_dropped = 0
        self.recording_error: str | None = None

    # ---- lifecycle -----------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def recording(self) -> bool:
        return self._rec_queue is not None

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
        self._log("starting shared dvgrab DV source", always=True)
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
        # flagging it as a failure.
        self.stop_recording()
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
                chunk = self._normalize_dif_chunk(chunk)
                if first:
                    loop.call_soon_threadsafe(self._log, "DV source emitted first bytes", True)
                    first = False
                rec = self._rec_queue
                if rec is not None and self.recording_error is None:
                    # Recording is the priority path: never intentionally drop DV
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
            self.recording_error = "DV source stopped while recording"
            self.stop_recording()
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

    def start_recording(self, path: Path) -> None:
        """Open ``path`` and route the live DV stream into it. Fast + sync."""
        if self.recording:
            raise RuntimeError("Already recording")
        self.recording_error = None
        self._rec_dropped = 0
        self._rec_path = path
        self._rec_handle = open(path, "wb", buffering=0)
        rec_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=self._rec_maxsize)
        self._rec_thread = threading.Thread(
            target=self._recording_writer, args=(rec_queue, self._rec_handle), daemon=True
        )
        self._rec_thread.start()
        # Publish last so the read loop never sees a half-initialised sink.
        self._rec_queue = rec_queue

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
        if handle is not None:
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:
                pass
            finally:
                handle.close()
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
                with open("/data/equip1-dvsource-debug.log", "a", encoding="utf-8") as handle:
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
