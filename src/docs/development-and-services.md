# Development and optional systemd services

Most development can run directly from the repository. The `src/systemd/` units and `src/scripts/` helpers are for an already-running Debian/Radxa OS, not the Buildroot appliance image.

## Python daemon development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r src/requirements.txt
PYTHONPATH=src python -m equip1d.main
```

Useful overrides:

```sh
EQUIP1_CAPTURE_DIR=$PWD/captures \
EQUIP1_HOST=127.0.0.1 \
EQUIP1_PORT=8000 \
PYTHONPATH=src python -m equip1d.main
```

Open the API at <http://127.0.0.1:8000/api/state>.

## OLED development without hardware

Use the browser designer for screen layout work:

```sh
PYTHONPATH=src python -m uis.oled.designer
```

Open <http://127.0.0.1:8765>.

To run the OLED app with mock display/input backends:

```sh
EQUIP1_OLED_MOCK=1 PYTHONPATH=src python -m uis.oled
```

## Web dashboard development

```sh
cd src/uis/web
npm install
npm run dev
```

Mock mode does not require the Python daemon or hardware:

```sh
npm run dev:mock
```

Static output used by the daemon:

```sh
npm run generate
```

The daemon serves `src/uis/web/.output/public` by default when it exists.

## Optional Debian/Radxa services

The service templates in `src/systemd/` run the app from `/opt/equip1` under an `equip1` user. They are useful on a stock OS during bring-up.

Install example:

```sh
sudo mkdir -p /opt/equip1/scripts
sudo install -m 0755 src/scripts/equip1-ap-nm.sh /opt/equip1/scripts/equip1-ap-nm.sh
sudo install -m 0755 src/scripts/equip1-hdmi-preview-fb.sh /opt/equip1/scripts/equip1-hdmi-preview-fb.sh
sudo install -m 0644 src/systemd/equip1-ap.service /etc/systemd/system/equip1-ap.service
sudo install -m 0644 src/systemd/equip1d.service /etc/systemd/system/equip1d.service
sudo install -m 0644 src/systemd/equip1-oled.service /etc/systemd/system/equip1-oled.service
sudo install -m 0644 src/systemd/equip1-hdmi-preview.service /etc/systemd/system/equip1-hdmi-preview.service
sudo systemctl daemon-reload
sudo systemctl enable --now equip1-ap.service equip1d.service equip1-oled.service equip1-hdmi-preview.service
```

## Helper scripts

| Script | Used by | Purpose |
| --- | --- | --- |
| `src/scripts/equip1-ap-nm.sh` | `src/systemd/equip1-ap.service` | Creates/updates a NetworkManager Wi-Fi access point |
| `src/scripts/equip1-hdmi-preview-fb.sh` | `src/systemd/equip1-hdmi-preview.service` | Streams `/api/stream.mkv?takeover=1` to `/dev/fb0` with ffmpeg |

The Buildroot image uses equivalent BusyBox-oriented scripts from `src/buildroot/overlay/`, not these development helpers.
