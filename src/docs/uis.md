# User interfaces

Equip-1 has two first-party user interfaces:

- an on-device OLED/buttons/LED UI in `src/uis/oled/`;
- a browser dashboard in `src/uis/web/`.

Both are API clients. They should not probe camera/storage hardware directly; they render daemon state from `/api/state` and send commands back to `equip1d`.

## OLED UI

Run locally:

```sh
PYTHONPATH=src python -m uis.oled
```

Important files:

| File | Purpose |
| --- | --- |
| `app.py` | Main loop, state polling, button navigation, command dispatch, LED state |
| `screens.py` | Screen renderers and per-screen button behavior |
| `api_client.py` | Minimal HTTP client for daemon state and commands |
| `display.py` | OLED display backend, font loading, mock display support |
| `input.py` | Buttons and buzzer backends, mock input support |
| `leds.py` | RGB LED SPI backend, boot marquee, status colors |
| `designer.py` | Browser-based OLED screen designer |

The OLED app polls `/api/state` at `ui.state_fetch_interval` and keeps a fallback offline state if the daemon is unreachable. If `state.power.available` is true, it also overlays a centered PiSugar battery percentage/icon in the header; otherwise the header is unchanged.

### OLED screens

Current screen order in `OledApp`:

1. `RecordingScreen` — record/stop, elapsed time, storage minutes.
2. `NetworkScreen` — AP/client/offline network details.
3. `UsbTransferScreen` — USB-C mass-storage mode controls.
4. `StorageScreen` — device kind, capacity, manual USB/SD switching.

`BootScreen` is shown for the boot animation before normal navigation starts.

### OLED designer

The designer renders the real `screens.py` drawing code in a browser without hardware:

```sh
PYTHONPATH=src python -m uis.oled.designer
```

Open <http://127.0.0.1:8765>. Use it when changing layout, fonts, or button-driven states.

## Web dashboard

The web dashboard is a static Nuxt app. During image builds, `src/buildroot/scripts/build.sh` runs `npm run generate` and the daemon serves `.output/public` from `/`.

Development:

```sh
cd src/uis/web
npm install
npm run dev
```

Mock mode, useful without hardware or the daemon:

```sh
cd src/uis/web
npm run dev:mock
```

Production static build:

```sh
cd src/uis/web
npm run generate
```

Important files:

| File | Purpose |
| --- | --- |
| `pages/index.vue` | Main dashboard UI and controls |
| `composables/useEquip1State.ts` | REST/WebSocket state, commands, mock recorder model |
| `composables/useEquip1Captures.ts` | Capture list and download URLs |
| `composables/useEquip1System.ts` | System stats polling |
| `assets/main.css` | Dashboard styling and responsive layout |
| `nuxt.config.ts` | Static SPA config, public API/WS base paths, PWA-ish metadata |

## Web live updates

`useEquip1State` connects to `/api/events` and periodically resyncs as a safety net:

- state resync every 3 seconds;
- captures resync every 10 seconds;
- command calls refresh state after completion.

Mock mode simulates recording growth, capture completion, thumbnails, and basic command errors entirely in the browser.

## UI settings

Common settings live in `/etc/equip1/equip-1.ini` under `[ui]`, with environment overrides:

| Setting | Env override | Default |
| --- | --- | --- |
| `api_base` | `EQUIP1_API_BASE` | `http://127.0.0.1:8000/api` |
| `api_timeout` | `EQUIP1_API_TIMEOUT` | `5.0` |
| `state_fetch_interval` | `EQUIP1_STATE_FETCH_INTERVAL` | `1.0` |
| `boot_duration_seconds` | `EQUIP1_BOOT_DURATION_SECONDS` | `3.0` |
| `boot_hold_seconds` | `EQUIP1_BOOT_HOLD_SECONDS` | `1.1` |
| `oled_fps` | `EQUIP1_OLED_FPS` | `8` |
| `pisugar_enabled` (`[power]`) | `EQUIP1_PISUGAR_ENABLED` | `true` |
| `pisugar_socket` (`[power]`) | `EQUIP1_PISUGAR_SOCKET` | `/tmp/pisugar-server.sock` |
| `pisugar_poll_interval` (`[power]`) | `EQUIP1_PISUGAR_POLL_INTERVAL` | `5` |
| `pisugar_timeout` (`[power]`) | `EQUIP1_PISUGAR_TIMEOUT` | `0.075` |

The web app uses Nuxt public runtime variables (`NUXT_PUBLIC_*`) for client-side API base, WebSocket base, mock mode, and performance logging.
