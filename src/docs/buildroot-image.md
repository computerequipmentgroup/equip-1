# Buildroot image

Equip-1 is Buildroot-first. The image build combines Buildroot configs, a rootfs overlay, custom package recipes for the DV capture stack, device-tree overlays, and the current application source.

## Build and flash

```sh
./src/buildroot/scripts/build.sh
./src/buildroot/scripts/flash.sh
```

Raspberry Pi 5 + PiSugar 3 Plus image:

```sh
./src/buildroot/scripts/build.sh equip1_pi5_pisugar3plus_defconfig
xz -T0 -9 -c src/buildroot/output/sdcard.img > src/buildroot/output/equip-1-v0.1.0-pi5-pisugar3plus.img.xz
```

`build.sh` expects the `equip1-builder` VM workflow used by this repository. It builds the Nuxt dashboard on the host, stages app sources into the overlay, syncs Buildroot inputs to the VM, runs Buildroot, and writes artifacts under `src/buildroot/output/`.

## Important paths

| Path | Purpose |
| --- | --- |
| `src/buildroot/configs/equip1_defconfig` | Buildroot defconfig |
| `src/buildroot/configs/linux.config` | ROCK 2F kernel config fragment |
| `src/buildroot/configs/linux-pi5.config` | Raspberry Pi 5 kernel config fragment |
| `src/buildroot/configs/u-boot.config` | ROCK 2F U-Boot config fragment |
| `src/buildroot/configs/genimage.cfg` | ROCK 2F disk image partition layout |
| `src/buildroot/configs/genimage-pi5.cfg` | Raspberry Pi 5 disk image partition layout |
| `src/buildroot/dts/` | DTS overlays compiled into `/boot/overlay-user/*.dtbo` |
| `src/buildroot/external/` | Buildroot external tree for `dvgrab` and FireWire libraries |
| `src/buildroot/overlay/` | Root filesystem overlay copied into the target image |
| `src/buildroot/scripts/post-build.sh` | Target rootfs post-build adjustments |
| `src/buildroot/scripts/build.sh` | Host/VM orchestration script |
| `src/docs/buildroot/` | Hardware and image operation notes formerly in `src/buildroot/docs/` |

## Application staging

Before the Buildroot VM build, `build.sh` stages the current source tree into the overlay:

- `src/equip1d/` → `src/buildroot/overlay/opt/equip1/equip1d/`
- `src/uis/` → `src/buildroot/overlay/opt/equip1/uis/`
- `src/fonts/` → `src/buildroot/overlay/opt/equip1/fonts/`
- `src/requirements.txt` → `src/buildroot/overlay/opt/equip1/requirements.txt`

This means the repository source remains authoritative; do not edit staged copies under `src/buildroot/overlay/opt/equip1/` by hand unless you are intentionally changing generated/staged content.

## Init script order

BusyBox init runs scripts in lexical order:

| Script | Responsibility |
| --- | --- |
| `S10loopback` | Bring up loopback networking |
| `S15data` | Prepare `/data` from USB-A storage or SD fallback |
| `S20boot-debug` | Optional early debug breadcrumbs |
| `S50network` | Start Wi-Fi AP, client mode, or disabled networking |
| `S60equip1d` | Start FastAPI daemon on port `8000` |
| `S61equip1-oled` | Start OLED/buttons UI |
| `S62equip1-hdmi-preview` | Start HDMI framebuffer preview watcher |
| `S98equip1-log-export` | Mirror logs from `/var/log/equip1/` into `/data/logs/` |
| `S99late-debug` | Optional late debug breadcrumbs |

## Build self-healing

`build.sh` applies a few targeted fixes before and between attempts:

- reasserts glibc toolchain settings if defconfig drifted to uClibc;
- removes an incompatible `CONFIG_DRM=n` override when Rockchip panel/DRM symbols fail;
- can force kernel, Python dependency, or ffmpeg cleanup on retry.

Environment knobs include `MAX_HEAL_ATTEMPTS`, `BUILD_JOBS`, `FORCE_KERNEL_CLEAN`, `FORCE_PYTHON_CLEAN`, `FORCE_PYTHON_DEPS`, and `FORCE_FFMPEG_CLEAN`.

## Runtime logs

Long-running service logs live under `/var/log/equip1/` so `/data` can be unmounted for storage switching and USB-C transfer mode. `equip1-export-logs` mirrors snapshots to `/data/logs/` when logging is not quiet.

Useful device commands:

```sh
/etc/init.d/S60equip1d restart
/etc/init.d/S61equip1-oled restart
/etc/init.d/S62equip1-hdmi-preview restart
tail -f /var/log/equip1/daemon.log
tail -f /var/log/equip1/oled.log
```

## Related docs

- [buildroot/equip1-app.md](buildroot/equip1-app.md)
- [buildroot/usb-recording-storage.md](buildroot/usb-recording-storage.md)
- [buildroot/enable-i2c-spi.md](buildroot/enable-i2c-spi.md)
- [buildroot/enable-pwr-en.md](buildroot/enable-pwr-en.md)
