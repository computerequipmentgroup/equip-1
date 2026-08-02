# Source documentation

This directory is the source-code documentation hub for Equip-1 / Firehat.

## Start here

- [System architecture](architecture.md) — how the daemon, shared DV/HDV source, UIs, storage, and image overlay fit together.
- [Daemon and HTTP API](daemon-api.md) — `src/equip1d/`, state model, commands, streaming endpoints, and WebSocket events.
- [DV/HDV stream, recording, and preview](dv-stream-recording-preview.md) — the single shared FireWire capture path used by recording, browser preview, and HDMI/VLC output.
- [Storage, captures, and USB modes](storage-captures-usb.md) — `/data/captures`, removable storage switching, USB-C mass-storage mode, and capture metadata.
- [MP4 export options](mp4-export.md) — post-recording sidecar export flow, OLED labels, quality presets, and settings/API values.
- [User interfaces](uis.md) — OLED/buttons UI, browser dashboard, local designer, and static web build.
- [Runtime settings](runtime-settings.md) — `/etc/equip1/equip-1.ini` sections and important environment overrides.
- [Buildroot image](buildroot-image.md) — image build flow, rootfs overlay, init ordering, and package fragments.
- [Development and optional services](development-and-services.md) — local daemon/UI workflows and Debian/Radxa systemd templates.

## Hardware and Buildroot notes moved here

The former `src/buildroot/docs/` notes now live under [`buildroot/`](buildroot/):

- [Buildroot application integration](buildroot/equip1-app.md)
- [USB recording storage](buildroot/usb-recording-storage.md)
- [Enable I2C/SPI overlays](buildroot/enable-i2c-spi.md)
- [Enable PCIe power regulator overlay](buildroot/enable-pwr-en.md)

## Runtime path map

Source paths are staged into the appliance image like this:

| Repository path | Device path | Purpose |
| --- | --- | --- |
| `src/equip1d/` | `/opt/equip1/equip1d/` | FastAPI daemon and recorder backend |
| `src/uis/` | `/opt/equip1/uis/` | OLED UI and generated/static web dashboard source |
| `src/fonts/` | `/opt/equip1/fonts/` | OLED fonts |
| `src/requirements.txt` | `/opt/equip1/requirements.txt` | Python runtime requirements |
| `src/buildroot/overlay/` | `/` | BusyBox init scripts, settings, helpers, boot files |

The Buildroot build script stages these files before syncing the overlay into the builder VM.
