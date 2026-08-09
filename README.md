![Equip-1 DV Recorder](gfx/README.md.png)

# Equip-1 ⚹ DV RECORDER

Equip-1 is an open-source, portable DV/HDV recorder for camcorders with FireWire/i.LINK/DV output. It is built around a Radxa ROCK 2F and a custom PCIe FireWire HAT, so you can mount it near a camera, power it from USB-C, press one button, and record tape footage directly to removable storage.

The project is for camera enthusiasts, videographers, film schools, archivists, and hardware/software contributors who want a modern, repairable path for capturing DV tapes without keeping an old laptop alive.

The [Firehat](https://github.com/computerequipmentgroup/firehat) is also available standalone. It works as a HAT for the ROCK 2F, Raspberry Pi 5, and other SBCs.

Website: <https://www.equip-1.c-e.group/>  
Community Discord: [discord.gg/wpXmcb5mvK](https://discord.gg/wpXmcb5mvK)

## Getting started

### 1. Get or build an image

Equip-1 is Buildroot-first. The image contains the recorder daemon, OLED/buttons UI, static web dashboard, Wi-Fi AP, storage handling, and HDMI preview service.

Prebuilt images are attached to GitHub releases:

<https://github.com/computerequipmentgroup/equip-1/releases>

Download the image for your hardware, decompress it if needed, and flash it to a microSD card. To build from source instead:

```bash
./src/buildroot/scripts/build.sh
./src/buildroot/scripts/flash.sh
```

The default runtime settings are baked into the image from:

```text
src/buildroot/overlay/etc/equip1/equip-1.ini
```

On a running device, edit the live settings file at:

```text
/etc/equip1/equip-1.ini
```

### 2. Connect to Equip-1

Default device access:

| Setting | Default |
| --- | --- |
| Wi-Fi SSID | `Equip-1` |
| Wi-Fi password | `firesecret` |
| Dashboard | `http://10.42.0.1:8000` |
| API base | `http://10.42.0.1:8000/api` |

Connect a phone or laptop to the Equip-1 Wi-Fi network, open the dashboard, attach a FireWire DV/HDV camera, and use the web UI or the device buttons to preview and record.

### 3. Prepare capture storage

Equip-1 records to `/data/captures` by default. At boot it prefers a non-root exFAT USB-A drive labelled `EQUIP1`; otherwise it falls back to the SD-card data partition when available.

Recommended USB storage format:

- filesystem: exFAT
- label: `EQUIP1`
- mount point on device: `/data`
- captures path: `/data/captures`

### 4. Record and export

Completed recordings are written as original `.dv` captures. By default, Equip-1 also creates same-stem `.mp4` sidecars in the background.

MP4 quality presets:

| Setting | OLED label | Use |
| --- | --- | --- |
| `small` | `[28]` | Smallest files |
| `balanced` | `[23]` | Middle ground |
| `high` | `[18]` | Default, close to source for most DV material |
| `max` | `[14]` | Highest quality, larger and slower |

See [`src/docs/mp4-export.md`](src/docs/mp4-export.md) for the full export flow.

## Runtime settings

User-facing device settings live at `/etc/equip1/equip-1.ini`. The default file is staged from `src/buildroot/overlay/etc/equip1/equip-1.ini`, and matching `EQUIP1_*` environment variables can override INI values for development or one-off debugging.

Example:

```ini
[network]
ap_ssid = Equip-1
ap_password = firesecret

[recording]
capture_dir = /data/captures
storage_label = EQUIP1
auto_convert_mp4 = true
mp4_quality = high
mp4_deinterlace = true
auto_storage_switch = true

[hdmi]
enabled = true

[logging]
log_level = info
```

## Docs

The full source documentation lives in `src/docs/` and covers the runtime settings, capture pipeline, storage behavior, user interfaces, and Buildroot image. Start with the topic that matches what you are changing, then follow the linked references for lower-level implementation details.

- [`src/docs/runtime-settings.md`](src/docs/runtime-settings.md) — `/etc/equip1/equip-1.ini` sections, common keys, and environment overrides.
- [`src/docs/mp4-export.md`](src/docs/mp4-export.md) — MP4 sidecar export flow, OLED labels, and quality presets.
- [`src/docs/storage-captures-usb.md`](src/docs/storage-captures-usb.md) — capture storage, `/data/captures`, USB switching, and USB-C mass-storage mode.
- [`src/docs/buildroot-image.md`](src/docs/buildroot-image.md) — image build flow, rootfs overlay, init ordering, and runtime logs.
- [`src/docs/daemon-api.md`](src/docs/daemon-api.md) — daemon state model, commands, HTTP endpoints, streams, and WebSocket events.
- [`src/docs/dv-stream-recording-preview.md`](src/docs/dv-stream-recording-preview.md) — FireWire capture path, recording, browser preview, and HDMI/VLC output.
- [`src/docs/uis.md`](src/docs/uis.md) — OLED/buttons UI, browser dashboard, local designer, and static web build.
- [`src/docs/development-and-services.md`](src/docs/development-and-services.md) — local development workflows and Debian/Radxa service templates.
- [`src/docs/architecture.md`](src/docs/architecture.md) — how the daemon, shared stream, UIs, storage, and image overlay fit together.

## Hardware

- Radxa ROCK 2F (Rockchip RK3528A, quad-core ARM Cortex-A53, 2 GB RAM)
- [Firehat](https://github.com/computerequipmentgroup/firehat)
- MicroSD storage
- USB-C power input, 5 V
- HDMI output
- Wi-Fi 6, Bluetooth 5.4
- 2× USB 2.0 Type-A
- 60 mm × 70 mm × 25 mm, ~100 g

## Repository structure

This is an open-source hardware product repository. Editable product sources, generated manufacturing files, source code, and graphics assets are kept separate:

- `hw/` — electronics, mechanical design, manufacturing exports, and validation notes.
- `src/` — recorder daemon, OLED/web UIs, Buildroot image tooling, and development service templates.
- `gfx/` — renders, photos, product images, diagrams, screenshots, and logos.

Key source paths:

- `src/equip1d/` — FastAPI recorder daemon. Owns camera detection, `dvgrab`, deck control, capture storage, preview streaming, and recorder state.
- `src/uis/oled/` — 128×64 OLED/buttons frontend for on-device control.
- `src/uis/web/` — Nuxt static web dashboard for phone/laptop control over the local Equip-1 Wi-Fi AP.
- `src/buildroot/` — appliance image, kernel/boot fragments, rootfs overlay, init scripts, and flash/build tooling.
- `src/docs/` — architecture, runtime settings, Buildroot, storage, UI, and export notes.

## Development

Install Python dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r src/requirements.txt
```

Run the daemon locally:

```bash
PYTHONPATH=src python -m equip1d.main
```

Design OLED screens in a browser without hardware:

```bash
PYTHONPATH=src python -m uis.oled.designer
```

Open <http://127.0.0.1:8765>. The designer renders the real `src/uis/oled/screens.py` drawing code to a 128×64 PNG, with screen/scenario selectors, button simulation, and editable state JSON.

Build the web dashboard:

```bash
cd src/uis/web
npm install
npm run generate
```

The daemon serves `src/uis/web/.output/public` when it exists.



## Open source

Hardware is licensed under [CERN OHL-S](https://ohwr.org/cern_ohl_s_v2.txt). Software is licensed under GPL. Derivatives must be released under the same licenses.
