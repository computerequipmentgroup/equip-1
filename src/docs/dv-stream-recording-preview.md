# DV stream, recording, and preview

The DV path is built around `src/equip1d/dvsource.py`. It keeps one FireWire capture process alive and fans the resulting bytes out to recording and preview consumers.

## Why there is one shared source

FireWire DV devices do not behave well when multiple processes compete for the camera. Older designs often stopped preview, started `dvgrab` for recording, then restarted preview later. That adds latency and can miss the first frames.

Current design:

1. When a camera is present, the daemon starts `dvgrab -buffers <n> -format raw -`.
2. A dedicated OS thread drains the stdout pipe with blocking reads.
3. Recording is toggled by opening or closing a file sink on the already-flowing bytes.
4. Preview subscribers receive copies through bounded queues.
5. If the camera disappears or `dvgrab` exits unexpectedly while recording, the recorder reports an error state.

## Recording path

Important files:

- `src/equip1d/dvsource.py` — owns the `dvgrab` process and the recording write thread.
- `src/equip1d/recorder.py` — records user intent and capture metadata.
- `src/equip1d/service.py` — validates camera/storage state, starts/stops recording, publishes events.

A start command does this:

1. Rejects the command if already recording or USB-C disk mode is active.
2. Probes for a camera.
3. Checks at least one minute of estimated free DV space.
4. Ensures the shared DV source is running.
5. Opens `capture_YYYYMMDD_HHMMSS.dv` in `/data/captures`.
6. Publishes the updated state.

A stop command closes the recording sink, runs `sync`, publishes captures immediately, then generates JPG thumbnails in the background and republishes captures.

## Preview path

`src/equip1d/preview.py` wraps `ffmpeg` around a `DvSource` subscription:

- `/api/preview.mjpg` transcodes DV to multipart MJPEG for browsers.
- `/api/stream.mkv` copies raw DV into a Matroska container for VLC and HDMI preview.

The two stream types share one busy lock. Only one preview/MKV consumer should be active at a time. `takeover=1` on `/api/stream.mkv` lets HDMI preempt a stale or browser-owned preview.

## Backpressure rules

Recording is the priority path:

- The `dvgrab` pipe is drained on a dedicated thread, not by the asyncio event loop.
- Preview queues are bounded and drop the oldest queued chunk if a consumer stalls.
- Recording has its own writer thread and queue.
- Browser or HDMI preview can glitch without blocking the FireWire read loop.

## DIF header normalization

Some camcorders emit DV DIF blocks that are playable but rejected by parts of `ffmpeg`/libavformat. `DvSource` can normalize the DIF block ID byte at 80-byte boundaries.

- Enabled by default: `EQUIP1_DV_NORMALIZE_DIF=1`
- Disable for debugging: `EQUIP1_DV_NORMALIZE_DIF=0`

## Useful tuning knobs

| Variable | Default | Purpose |
| --- | --- | --- |
| `EQUIP1_DV_BUFFERS` | `50` | `dvgrab -buffers` ring size |
| `EQUIP1_DV_PIPE_BYTES` | `1048576` | Target kernel pipe size between `dvgrab` and reader |
| `EQUIP1_DV_RECORD_QUEUE` | `2048` | Recording writer queue length |
| `EQUIP1_DV_PREVIEW_QUEUE` | `32` | Preview subscriber queue length |
| `EQUIP1_PREVIEW_FPS` | `25` | Idle browser preview FPS |
| `EQUIP1_PREVIEW_SIZE` | `720:540` | Idle browser preview size |
| `EQUIP1_PREVIEW_RECORDING_FPS` | `2` | Browser preview FPS while recording |
| `EQUIP1_PREVIEW_RECORDING_SIZE` | `480:360` | Browser preview size while recording |
| `EQUIP1_PREVIEW_STALE_SECONDS` | `12` | Age after which an active stream can be treated as stale |

Prefer changing preview FPS/size before changing DV queue sizes.
