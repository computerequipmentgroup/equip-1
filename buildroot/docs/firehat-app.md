# Firehat application integration

The Buildroot image stages this desktop repo into `/opt/firehat` at build time.

`buildroot/scripts/build.sh` copies:

- `firehatd/` to `/opt/firehat/firehatd`
- `uis/` to `/opt/firehat/uis`
- `fonts/` to `/opt/firehat/fonts`
- `requirements.txt` to `/opt/firehat/requirements.txt`

Runtime-only helper scripts live directly in the Buildroot overlay under
`buildroot/overlay/opt/firehat/scripts/`; they are not copied from a repo-root
`scripts/` directory.

During the VM build it installs Python dependencies into `/opt/firehat/lib` in the overlay and then Buildroot packs that overlay into the root filesystem.

BusyBox init starts the app with:

- `/etc/init.d/S60firehatd` — FastAPI recorder daemon on port `8000`
- `/etc/init.d/S61firehat-oled` — OLED/button UI talking to `127.0.0.1:8000`
- `/etc/init.d/S62firehat-hdmi-preview` — HDMI framebuffer preview watcher

Recordings default to `/data/captures`, which is prepared by `/etc/init.d/S15data`. USB-A capture storage is documented in [`usb-recording-storage.md`](usb-recording-storage.md).

Useful device commands:

```sh
/etc/init.d/S60firehatd restart
/etc/init.d/S61firehat-oled restart
tail -f /var/log/firehatd.log
tail -f /var/log/firehat-oled.log
```
