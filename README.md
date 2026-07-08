# Equip-1

Equip-1 is an open-source, portable DV recorder for camcorders with FireWire/i.LINK/DV output. It is built around a Radxa ROCK 2F and a custom PCIe FireWire HAT, so you can mount it near a camera, power it from USB-C, press one button, and record tape footage directly to removable storage.

The project is for camera enthusiasts, videographers, film schools, archivists, and hardware/software contributors who want a modern, repairable path for capturing DV tapes without keeping an old laptop alive.

Website: <https://www.equip-1.c-e.group/>

## What is in this repo?

- `equip1d/` — FastAPI recorder daemon. Owns camera detection, `dvgrab`, deck control, capture storage, preview streaming, and recorder state.
- `uis/oled/` — 128×64 OLED/buttons frontend for on-device control.
- `uis/web/` — Nuxt static web dashboard for phone/laptop control over the local Equip-1 Wi-Fi AP.
- `buildroot/` — appliance image, kernel/boot fragments, rootfs overlay, init scripts, and flash/build tooling.
- `systemd/` — optional Debian/Radxa service templates for development outside the Buildroot image.
- `scripts/` — helper scripts used by the optional systemd install path.

## Product goals

Equip-1 aims to be:

- **Simple in the field** — connect FireWire, power from USB-C, press record.
- **Archive friendly** — record raw DV to removable media with predictable filenames and local web download.
- **Self-contained** — OLED controls, Wi-Fi dashboard, HDMI preview, and optional USB-C disk mode.
- **Hackable** — Buildroot-first system image, Python daemon, web UI, documented init scripts, and commodity Linux tooling.
- **Community maintainable** — open hardware/software direction, clear seams for camera/deck support, UI improvements, storage workflows, testing, and docs.

## Hardware/software snapshot

The current target device uses:

- Radxa ROCK 2F / RK3528A
- Custom PCIe FireWire HAT
- USB-C 5V power
- microSD system/recording storage, with exFAT recording partition support
- Wi-Fi 6 / Bluetooth 5.4 on the base board
- OLED/buttons UI, HDMI preview, and FireWire tape deck control where supported

## Development setup

Install Python dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run the daemon locally:

```bash
python -m equip1d.main
```

Run the OLED client in mock mode:

```bash
EQUIP1_OLED_MOCK=1 python -m uis.oled
```

Mock OLED keys: `u` = up, `d` = down, `s` = select.

Design OLED screens in a browser without OLED hardware:

```bash
python -m uis.oled.designer
```

Open <http://127.0.0.1:8765>. The designer renders the real `uis/oled/screens.py` drawing code to a 128×64 PNG, with screen/scenario selectors, button simulation, and editable state JSON.

Build the web dashboard:

```bash
cd uis/web
npm install
npm run generate
```

The daemon serves `uis/web/.output/public` when it exists.

Deck control uses `dvcont` from `libavc1394-tools` when available:

```bash
sudo apt install -y libavc1394-tools
```

Override the binary path with `EQUIP1_DVCONT_BIN`.

## Buildroot device image

Equip-1 is Buildroot-first. The Buildroot overlay stages runtime files into `/opt/equip1` and BusyBox init starts the recorder daemon, OLED UI, Wi-Fi access point, storage handling, and HDMI preview.

Build and flash:

```bash
./buildroot/scripts/build.sh
./buildroot/scripts/flash.sh
```

Default device access:

- SSID: `Equip-1`
- Password: `firesecret`
- Device URL: `http://10.42.0.1:8000`
- Wi-Fi interface: `wlan0`
- Settings file: `/etc/equip1/equip-1.ini`

Override device settings in `buildroot/overlay/etc/equip1/equip-1.ini` before building, or edit `/etc/equip1/equip-1.ini` on the device. Runtime environment variables use the `EQUIP1_` prefix.

The HDMI framebuffer preview watcher lives at `/opt/equip1/scripts/equip1-hdmi-preview-fb.sh`. It watches `/sys/class/drm/*HDMI*/status`; when a monitor is plugged in it starts ffmpeg and renders the live DV stream to `/dev/fb0`, and unplugging the monitor stops ffmpeg again. It writes diagnostics to `/data/hdmi-preview.log` on the `EQUIP1` recordings partition.

## Debian/Radxa systemd development install

This path is for development on an already-running Debian/Radxa OS. The Buildroot image remains the appliance path.

```bash
sudo mkdir -p /opt/equip1/scripts
sudo install -m 0755 scripts/equip1-ap-nm.sh /opt/equip1/scripts/equip1-ap-nm.sh
sudo install -m 0755 scripts/equip1-hdmi-preview-fb.sh /opt/equip1/scripts/equip1-hdmi-preview-fb.sh
sudo install -m 0644 systemd/equip1-ap.service /etc/systemd/system/equip1-ap.service
sudo install -m 0644 systemd/equip1d.service /etc/systemd/system/equip1d.service
sudo install -m 0644 systemd/equip1-oled.service /etc/systemd/system/equip1-oled.service
sudo install -m 0644 systemd/equip1-hdmi-preview.service /etc/systemd/system/equip1-hdmi-preview.service
sudo systemctl daemon-reload
sudo systemctl enable --now equip1-ap.service equip1d.service equip1-oled.service equip1-hdmi-preview.service
```

## Ways to contribute

Good first areas for contributors:

- Test DV capture and deck control across more camcorder models.
- Improve archive workflows: file naming, metadata sidecars, checksums, ingest notes, and batch export.
- Harden storage and USB-C disk mode behavior across SD cards and USB drives.
- Refine OLED/web UX for non-technical operators.
- Improve Buildroot reproducibility, diagnostics, and emulator coverage.
- Write docs for capture practices, hardware assembly, troubleshooting, and classroom/archive deployments.

## API

- `GET /api/state`
- `GET /api/storage`
- `GET /api/system`
- `GET /api/captures`
- `GET /api/captures/{capture_name}/download`
- `POST /api/time`
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

## Naming

The product is **Equip-1**. Code/package names use `equip1`/`equip1d`, environment variables use `EQUIP1_`, and the recordings partition label is `EQUIP1`.
