# Runtime settings

Equip-1 reads user-facing settings from:

```text
/etc/equip1/equip-1.ini
```

The default file is stored in the Buildroot overlay at `src/buildroot/overlay/etc/equip1/equip-1.ini`. Environment variables with matching `EQUIP1_*` names override INI values, which is useful for development and one-off debugging.

## Settings loader

- Python code uses `src/equip1d/settings.py`.
- BusyBox init scripts source `src/buildroot/overlay/etc/equip1/settings-env.sh` and call `equip1_ini_default` to export defaults.
- Light settings are persisted by the daemon back into the INI file.

## Main INI sections

### `[recording]`

| Key | Common env override | Purpose |
| --- | --- | --- |
| `capture_dir` | `EQUIP1_CAPTURE_DIR` | Capture directory, normally `/data/captures` |
| `storage_label` | `EQUIP1_DATA_LABEL` | Preferred USB-A exFAT label, normally `EQUIP1` |
| `data_mount` | `EQUIP1_DATA_MNT` | Mount point for recordings, normally `/data` |
| `data_mount_options` | `EQUIP1_DATA_MOUNT_OPTS` | Mount options, normally `noatime` |
| `auto_storage_switch` | `EQUIP1_AUTO_STORAGE_SWITCH` | Enable idle USB/SD automatic switching |
| `auto_storage_cooldown_seconds` | `EQUIP1_AUTO_STORAGE_COOLDOWN_SECONDS` | Minimum spacing between auto-switch attempts |
| `normalize_dif_headers` | `EQUIP1_DV_NORMALIZE_DIF` | Enable DV DIF header normalization |

### `[network]`

| Key | Common env override | Purpose |
| --- | --- | --- |
| `wifi_mode` | `EQUIP1_WIFI_MODE` | `ap`, `client`, or `off` |
| `host` | `EQUIP1_HOST` | Daemon bind host, default `0.0.0.0` |
| `port` | `EQUIP1_PORT` | Daemon/API port, default `8000` |
| `ap_enabled` | `EQUIP1_AP_ENABLED` | Include AP details in daemon state |
| `ap_iface` | `EQUIP1_AP_IFACE` | AP network interface, default `wlan0` |
| `ap_ssid` | `EQUIP1_AP_SSID` | Access-point SSID |
| `ap_password` | `EQUIP1_AP_PASSWORD` | Access-point password |
| `ap_ip` | `EQUIP1_AP_IP` | Access-point IP, default `10.42.0.1` |
| `captive_port` | `EQUIP1_CAPTIVE_PORT` | Optional captive redirect server port |

### `[preview]`

| Key | Env override | Purpose |
| --- | --- | --- |
| `fps` | `EQUIP1_PREVIEW_FPS` | Browser MJPEG preview FPS while idle |
| `size` | `EQUIP1_PREVIEW_SIZE` | Browser MJPEG preview size while idle |
| `quality` | `EQUIP1_PREVIEW_QUALITY` | MJPEG quality while idle |
| `recording_fps` | `EQUIP1_PREVIEW_RECORDING_FPS` | Lower FPS while recording |
| `recording_size` | `EQUIP1_PREVIEW_RECORDING_SIZE` | Lower size while recording |
| `recording_quality` | `EQUIP1_PREVIEW_RECORDING_QUALITY` | MJPEG quality while recording |
| `filter` | `EQUIP1_PREVIEW_FILTER` | Full custom idle ffmpeg video filter |
| `recording_filter` | `EQUIP1_PREVIEW_RECORDING_FILTER` | Full custom recording ffmpeg video filter |

### `[ui]`

| Key | Env override | Purpose |
| --- | --- | --- |
| `api_base` | `EQUIP1_API_BASE` | OLED API base URL |
| `api_timeout` | `EQUIP1_API_TIMEOUT` | OLED HTTP timeout |
| `state_fetch_interval` | `EQUIP1_STATE_FETCH_INTERVAL` | OLED polling interval |
| `oled_fps` | `EQUIP1_OLED_FPS` | OLED render loop FPS |
| `boot_duration_seconds` | `EQUIP1_BOOT_DURATION_SECONDS` | Boot animation duration |
| `boot_hold_seconds` | `EQUIP1_BOOT_HOLD_SECONDS` | Boot logo hold time |

### `[lights]`

| Key | Purpose |
| --- | --- |
| `enabled` | Enables normal/status RGB LED output |
| `default_colors` | Semicolon-separated `r,g,b` triples for each LED |
| `brightness` | Runtime brightness multiplier, `0.0` to `1.0` |

The web UI changes these values over `WS /api/events`; the daemon writes them atomically.

### `[hdmi]`

| Key | Env override | Purpose |
| --- | --- | --- |
| `enabled` | `EQUIP1_HDMI_PREVIEW_ENABLED` | Start the HDMI preview watcher |
| `stream_url` | `EQUIP1_HDMI_STREAM_URL` | MKV stream URL, usually `/api/stream.mkv?takeover=1` |
| `fbdev` | `EQUIP1_HDMI_FBDEV` | Framebuffer device, default `/dev/fb0` |
| `poll_seconds` | `EQUIP1_HDMI_POLL_SECONDS` | HDMI status polling interval |
| `pix_fmt` | `EQUIP1_HDMI_PIX_FMT` | Override framebuffer pixel format |

### `[logging]`

| Key | Env override | Purpose |
| --- | --- | --- |
| `log_level` | `EQUIP1_LOG_LEVEL` | `quiet`, `error`, `warning`, `info`, or `debug` |

Debug logging also enables more verbose performance/debug output in several paths.

## Development-only and low-level knobs

Use these sparingly:

- `EQUIP1_DV_BUFFERS`, `EQUIP1_DV_PIPE_BYTES`, `EQUIP1_DV_RECORD_QUEUE`, `EQUIP1_DV_PREVIEW_QUEUE` for shared DV source buffering.
- `EQUIP1_DVGRAB_BIN`, `EQUIP1_DVCONT_BIN`, `EQUIP1_FFMPEG_BIN` to run alternate binaries.
- `EQUIP1_WEB_DIR` to serve a different static dashboard directory.
- `EQUIP1_OLED_MOCK=1` to run OLED code without hardware.
- `EQUIP1_PERF_THRESHOLD_MS` to adjust performance log threshold.
