# Daemon and HTTP API

The daemon is the source of truth for recorder state and control. It is started with:

```sh
PYTHONPATH=src python -m equip1d.main
```

On the appliance image, `S60equip1d` runs the same module from `/opt/equip1`.

## Main modules

- `src/equip1d/main.py` — entrypoint, Uvicorn startup, optional captive portal redirect server.
- `src/equip1d/api.py` — FastAPI routes, streaming responses, WebSocket endpoint, static web dashboard mount.
- `src/equip1d/service.py` — `Equip1Daemon`, command validation, monitor loop, state snapshots, event publishing.
- `src/equip1d/models.py` — dataclass state model returned by `/api/state`.
- `src/equip1d/camera.py` and `deck.py` — FireWire camera detection and on-demand AV/C deck commands.
- `src/equip1d/settings.py` — shared INI settings loader/saver.

## Daemon modes

`state.mode` is one of:

| Mode | Meaning |
| --- | --- |
| `idle` | Camera detected, storage has room, ready to record |
| `no_camera` | No usable DV/HDV camera detected |
| `recording` | A capture file is currently being written |
| `storage_full` | Less than one minute of estimated capture capacity remains |
| `mounting` | `/data` is being mounted, remounted, or switched |
| `usb_transfer` | `/data` is exported over USB-C mass-storage mode |
| `converting` | A completed `.dv` capture is being converted to MP4 |
| `error` | A command, monitor, recorder, storage, or USB operation failed |

`models.py` also reserves `booting` and `stopping` for UI/state compatibility. While `mounting` or `usb_transfer`, captures are hidden and live streaming is disabled.

## REST endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/state` | Full daemon state snapshot |
| `GET` | `/api/storage` | `state.storage` only |
| `GET` | `/api/system` | CPU, memory, model, and temperature stats |
| `GET` | `/api/captures` | Capture files and thumbnail/download URLs |
| `GET` | `/api/captures/{name}/download` | Download a capture file by safe basename |
| `GET` | `/api/captures/{name}/thumbnail` | Download generated JPG thumbnail |
| `GET` | `/api/preview.mjpg` | Browser MJPEG preview stream |
| `GET` | `/api/stream.mkv` | Live DV or HDV copied into a Matroska stream for VLC/HDMI |
| `POST` | `/api/time` | Set device clock from browser time only if clock is unset |
| `POST` | `/api/settings/conversion` | Set automatic `.dv` to `.mp4` conversion and MP4 quality |
| `POST` | `/api/settings/auto-storage-switch` | Enable/disable idle USB/SD automatic switching |
| `POST` | `/api/settings/hdmi-preview` | Persist HDMI preview enabled/disabled for the preview watcher |
| `POST` | `/api/settings/lights` | Set LED enabled/disabled state |
| `POST` | `/api/commands/start-recording` | Start recording to `/data/captures` |
| `POST` | `/api/commands/stop-recording` | Stop recording and schedule thumbnails |
| `POST` | `/api/commands/rescan-camera` | Publish a fresh state snapshot |
| `POST` | `/api/commands/deck-play` | Send AV/C play command with `dvcont` |
| `POST` | `/api/commands/deck-stop` | Send AV/C stop command |
| `POST` | `/api/commands/deck-rewind` | Send AV/C rewind command |
| `POST` | `/api/commands/deck-fast-forward` | Send AV/C fast-forward command |
| `POST` | `/api/commands/clear-error` | Clear current error and republish state |
| `POST` | `/api/commands/usb-storage-start` | Stop capture/preview and export `/data` over USB-C |
| `POST` | `/api/commands/usb-storage-stop` | Stop USB-C mass-storage mode and remount `/data` |
| `POST` | `/api/commands/storage-switch-usb` | Manually switch `/data` to USB-A storage |
| `POST` | `/api/commands/storage-switch-sd` | Manually switch `/data` back to SD fallback |

Command failures are returned as HTTP `409` with a text `detail`. User errors such as invalid time payloads are `400`; missing files are `404`.

`state.camera.format` is `"unknown"`, `"dv"`, or `"hdv"`. It starts as `"unknown"` after a camera appears and changes once the shared `dvgrab` stream emits enough bytes to classify the source. Recordings use `.dv` for raw DV and `.m2t` for native HDV/MPEG-TS.

## WebSocket events

`WS /api/events` sends an initial `state`, an initial `captures`, then future daemon events:

```json
{ "type": "state", "state": { "mode": "idle" }, "server_sent_at": 1783720000.0 }
{ "type": "captures", "captures": [], "server_sent_at": 1783720001.0 }
```

The WebSocket also accepts settings messages from the web UI:

```json
{ "type": "set-light-color", "colors": [[0, 0, 255], [0, 0, 255], [0, 0, 255]] }
{ "type": "set-lights-enabled", "enabled": true }
{ "type": "set-lights-brightness", "brightness": 0.25 }
{ "type": "set-auto-convert-mp4", "enabled": true }
```

Light, conversion, storage, and HDMI settings are persisted through `Equip1Settings` into `/etc/equip1/equip-1.ini`. The OLED UI uses the REST settings endpoints.

## Static dashboard serving

At startup `api.py` mounts `EQUIP1_WEB_DIR` at `/` when it exists. The default is:

```text
src/uis/web/.output/public
```

The Buildroot build runs `npm run generate` and stages this output into `/opt/equip1/uis/web/.output/public`.
