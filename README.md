# Firehat

Firehat is moving from a single 20 Hz Python loop into a headless recorder daemon plus thin UIs.

## Pieces

- `firehatd/` — FastAPI daemon that owns camera detection, `dvgrab`, capture storage, recorder state, and commands.
- `uis/oled/` — OLED/buttons frontend. It polls the daemon API and sends commands; it does not own recording.
- `uis/web/` — Nuxt static SPA for browser/phone control.
- `buildroot/` — Buildroot appliance image, overlay, init scripts, and flash tooling.
- `systemd/` — optional Debian/Radxa unit templates for the daemon, OLED client, AP, and HDMI ffmpeg preview.
- `scripts/` — helper scripts used by the optional systemd install path.

## Development

Install Python dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run daemon:

```bash
python -m firehatd.main
```

Run OLED client in mock mode:

```bash
FIREHAT_OLED_MOCK=1 python -m uis.oled
```

Keys in mock OLED mode: `u` = up, `d` = down, `s` = select.

Design OLED screens in a browser without OLED hardware:

```bash
python -m uis.oled.designer
```

Open <http://127.0.0.1:8765>. The designer renders the real `uis/oled/screens.py` drawing code to a 128×64 PNG, with screen/scenario selectors, button simulation, and editable state JSON.

Build Nuxt static frontend:

```bash
cd uis/web
npm install
npm run generate
```

The daemon serves `uis/web/.output/public` if it exists.

Deck control uses `dvcont` from `libavc1394-tools` when available:

```bash
sudo apt install -y libavc1394-tools
```

Override the binary path with `FIREHAT_DVCONT_BIN`.

## Buildroot device image

Firehat is Buildroot-first. The Buildroot overlay stages runtime files into `/opt/firehat` and BusyBox init starts the recorder daemon, OLED UI, Wi-Fi access point, and HDMI preview.

Build and flash:

```bash
./buildroot/scripts/build.sh
./buildroot/scripts/flash.sh
```

Default Wi-Fi AP settings:

- SSID: `Equip-1`
- Password: `firesecret`
- Device URL: `http://10.42.0.1:8000`
- Wi-Fi interface: `wlan0`

Override device settings in `buildroot/overlay/etc/firehat/equip-1.ini` before building, or edit `/etc/firehat/equip-1.ini` on the device.

The Buildroot image includes an HDMI framebuffer preview watcher at `/opt/firehat/scripts/firehat-hdmi-preview-fb.sh`. It watches `/sys/class/drm/*HDMI*/status`; when a monitor is plugged in it starts ffmpeg and renders the live DV stream directly to `/dev/fb0`, and unplugging the monitor stops ffmpeg again. It writes diagnostics to `/data/hdmi-preview.log` on the EQUIP1 partition. Override `[hdmi]` settings in `/etc/firehat/equip-1.ini` or set `FIREHAT_HDMI_STATUS_FILES` if the board uses different connector paths.

## Debian/Radxa systemd install

This path is kept for development on an already-running Debian/Radxa OS. Buildroot remains the appliance-image path.

```bash
sudo mkdir -p /opt/firehat/scripts
sudo install -m 0755 scripts/firehat-ap-nm.sh /opt/firehat/scripts/firehat-ap-nm.sh
sudo install -m 0755 scripts/firehat-hdmi-preview-fb.sh /opt/firehat/scripts/firehat-hdmi-preview-fb.sh
sudo install -m 0644 systemd/firehat-ap.service /etc/systemd/system/firehat-ap.service
sudo install -m 0644 systemd/firehatd.service /etc/systemd/system/firehatd.service
sudo install -m 0644 systemd/firehat-oled.service /etc/systemd/system/firehat-oled.service
sudo install -m 0644 systemd/firehat-hdmi-preview.service /etc/systemd/system/firehat-hdmi-preview.service
sudo systemctl daemon-reload
sudo systemctl enable --now firehat-ap.service firehatd.service firehat-oled.service firehat-hdmi-preview.service
```

The HDMI systemd unit is an ffmpeg framebuffer preview, not a browser kiosk.

On the OLED `NETWORK` screen, press the middle/select button to show a Wi-Fi QR code. Phones can scan it to join the `Equip-1` network directly. Press middle/select again, or press up/down once, to leave the QR view.

## API

- `GET /api/state`
- `GET /api/storage`
- `GET /api/captures`
- `POST /api/commands/start-recording`
- `POST /api/commands/stop-recording`
- `POST /api/commands/rescan-camera`
- `POST /api/commands/deck-play`
- `POST /api/commands/deck-stop`
- `POST /api/commands/deck-rewind`
- `POST /api/commands/deck-fast-forward`
- `POST /api/commands/clear-error`
- `POST /api/commands/shutdown`
- `POST /api/commands/reboot`
- `WS /api/events`
