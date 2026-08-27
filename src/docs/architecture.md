# System architecture

Equip-1 is a small appliance around one central process: the `equip1d` daemon. The daemon owns camera discovery, the shared DV/HDV byte stream, recording state, storage state, preview streaming, and API events. The OLED UI and web dashboard are clients of that API.

```text
DV/HDV camera / FireWire
        │
        ▼
  dvgrab shared source       /data/captures
  src/equip1d/dvsource.py ───────┬── recording sink (.mov/.dv/.avi/.m2t files)
        │                        │
        ├── ffmpeg MJPEG ────────┼── GET /api/preview.mjpg
        └── ffmpeg MKV copy ─────┴── GET /api/stream.mkv

FastAPI daemon (src/equip1d/api.py, service.py)
        │
        ├── OLED UI (src/uis/oled) polls /api/state and posts commands
        ├── Web UI (src/uis/web) uses REST + /api/events WebSocket
        ├── BusyBox init scripts in src/buildroot/overlay/etc/init.d
        └── helper scripts in src/buildroot/overlay/usr/sbin and /opt/equip1/scripts
```

## Core principles

- **One FireWire owner:** `DvSource` starts one long-lived `dvgrab -format raw -` process when a camera is present. dvgrab/AV-C and first-byte stream detection classify the stream as raw DV or native HDV/MPEG-TS, and recording/preview consume that same byte stream instead of fighting for the camera.
- **Recording is priority:** preview subscribers use bounded drop-oldest queues. If a browser or HDMI stream stalls, preview glitches before recording is allowed to back up.
- **State is centralized:** `Equip1Daemon.snapshot()` returns a single `DaemonState` object. UIs should render from this state rather than duplicating hardware probes.
- **Device settings are INI-backed:** `/etc/equip1/equip-1.ini` is the persistent user-facing settings file. Environment variables still override it for development and debugging.
- **Image is overlay-first:** the Buildroot overlay contains the init scripts and helper binaries; `src/buildroot/scripts/build.sh` stages current app sources into `/opt/equip1` before the image build.

## Important source areas

| Path | Responsibility |
| --- | --- |
| `src/equip1d/service.py` | High-level daemon orchestration: modes, commands, monitor loop, event publishing |
| `src/equip1d/api.py` | FastAPI routes, WebSocket event stream, static web mount |
| `src/equip1d/dvsource.py` | Long-lived `dvgrab` process, DV/HDV stream detection, threaded pipe drain, recording sink, preview fan-out |
| `src/equip1d/preview.py` | `ffmpeg` MJPEG preview and Matroska live stream wrappers |
| `src/equip1d/storage.py` | Capture listing, safe path lookup, storage capacity, thumbnails |
| `src/uis/oled/` | On-device OLED/buttons/LED UI and browser-based OLED designer |
| `src/uis/web/` | Nuxt dashboard, mock mode, captures/system/stream controls |
| `src/buildroot/` | Buildroot configs, external packages, DTS overlays, rootfs overlay, build/flash scripts |
| `src/systemd/` and `src/scripts/` | Optional Debian/Radxa development service templates and helpers |

## Normal boot flow in the image

1. Kernel and device-tree overlays boot from `src/buildroot/overlay/boot/`.
2. BusyBox init runs `src/buildroot/overlay/etc/init.d/S*` scripts.
3. `S15data` prepares `/data` and `/data/captures` from USB storage or the SD fallback partition.
4. `S50network` starts access-point, client, or disabled Wi-Fi mode.
5. `S60equip1d` exports settings and starts the FastAPI daemon on port `80`.
6. `S61equip1-oled` starts the OLED/buttons UI against `http://127.0.0.1/api`.
7. `S62equip1-hdmi-preview` watches HDMI status and opens `/api/stream.mkv?takeover=1` when needed.
8. `S98equip1-log-export` mirrors selected logs from `/var/log/equip1/` to `/data/logs/`.
