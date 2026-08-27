# Equip-1 application integration

The Buildroot image stages the `src/` tree into `/opt/equip1` at build time.

`src/buildroot/scripts/build.sh` copies:

- `src/equip1d/` to `/opt/equip1/equip1d`
- `src/uis/` to `/opt/equip1/uis`
- `src/fonts/` to `/opt/equip1/fonts`
- `src/requirements.txt` to `/opt/equip1/requirements.txt`

Runtime-only helper scripts live directly in the Buildroot overlay under
`src/buildroot/overlay/opt/equip1/scripts/`; they are not copied from a
`src/scripts/` directory.

During the VM build it installs Python dependencies into `/opt/equip1/lib` in the overlay and then Buildroot packs that overlay into the root filesystem.

BusyBox init starts the app with:

- `/etc/init.d/S60equip1d` — FastAPI recorder daemon on port `80`
- `/etc/init.d/S61equip1-oled` — OLED/button UI talking to `127.0.0.1`
- `/etc/init.d/S62equip1-hdmi-preview` — HDMI framebuffer preview watcher

Recordings default to `/data/captures`, which is prepared by `/etc/init.d/S15data`. USB-A capture storage is documented in [`usb-recording-storage.md`](usb-recording-storage.md).

Useful device commands:

```sh
/etc/init.d/S60equip1d restart
/etc/init.d/S61equip1-oled restart
tail -f /var/log/equip1/daemon.log
tail -f /var/log/equip1/oled.log
```
