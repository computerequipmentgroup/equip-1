# Firehat

Firehat is moving from a single 20 Hz Python loop into a headless recorder daemon plus thin UIs.

## Pieces

- `firehatd/` — FastAPI daemon that owns camera detection, `dvgrab`, capture storage, recorder state, and commands.
- `uis/oled/` — OLED/buttons frontend. It polls the daemon API and sends commands; it does not own recording.
- `uis/web/` — Nuxt static SPA for browser/HDMI use.
- `systemd/` — unit templates for the daemon, OLED client, and kiosk Chromium.

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

## Radxa Wi-Fi access point

Firehat can bring up its own Wi-Fi so phones can join the device directly and open the web UI served by `firehatd`.

Defaults:

- SSID: `Equip-1`
- Password: `firesecret`
- Device URL: `http://10.42.0.1:8000`
- Wi-Fi interface: `wlan0`

The access point uses NetworkManager (`nmcli`) with IPv4 sharing, so NetworkManager provides DHCP/DNS to connected phones.

On the Radxa Rock 2F, build the web UI, copy/symlink this repo to `/opt/firehat`, then install the units:

```bash
sudo install -m 0755 scripts/firehat-ap-nm.sh /opt/firehat/scripts/firehat-ap-nm.sh
sudo install -m 0644 systemd/firehat-ap.service /etc/systemd/system/firehat-ap.service
sudo install -m 0644 systemd/firehatd.service /etc/systemd/system/firehatd.service
sudo systemctl daemon-reload
sudo systemctl enable --now firehat-ap.service firehatd.service
```

Override AP settings in `/etc/firehat/ap.env`:

```bash
sudo mkdir -p /etc/firehat
sudo tee /etc/firehat/ap.env >/dev/null <<'EOF'
FIREHAT_AP_IFACE=wlan0
FIREHAT_AP_SSID=Equip-1
FIREHAT_AP_PASSWORD=firesecret
FIREHAT_AP_IP=10.42.0.1/24
EOF
sudo systemctl restart firehat-ap.service firehatd.service
```

If `firehat-ap.service` fails, check that NetworkManager is running and that the Wi-Fi adapter supports AP mode (`iw list` should include `* AP`).

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
