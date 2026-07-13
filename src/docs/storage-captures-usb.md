# Storage, captures, and USB modes

Equip-1 records into `/data/captures`. The daemon does not need to know whether `/data` is backed by USB-A storage, SD fallback storage, or another mount; it uses `StorageManager` to inspect the active mount and list captures safely.

## Source files

- `src/equip1d/storage.py` — storage capacity snapshots, capture list, safe capture/thumbnail path lookup, thumbnail generation.
- `src/equip1d/service.py` — storage switch orchestration, USB-C disk-mode orchestration, capture event publishing.
- `src/buildroot/overlay/etc/init.d/S15data` — boot-time `/data` mount selection.
- `src/buildroot/overlay/usr/sbin/equip1-storage-switch` — runtime switch between USB-A storage and SD fallback.
- `src/buildroot/overlay/usr/sbin/equip1-usb-storage` — USB-C mass-storage gadget export for the active `/data` block device.

## `/data` mount selection

At boot, `S15data` creates `/data/captures` and chooses storage in this order:

1. A non-root exFAT partition labelled `EQUIP1`.
2. If no labelled partition exists, exactly one non-root exFAT partition.
3. SD/rootfs fallback partition.

See [buildroot/usb-recording-storage.md](buildroot/usb-recording-storage.md) for operator-level USB preparation and expected logs.

## Runtime storage switching

While idle, the daemon monitor loop can automatically switch storage:

- USB-A inserted: attempt switch to USB.
- Active USB-A removed: attempt switch back to SD fallback.
- Recording or USB-C transfer active: do not switch.

Manual API commands are also available:

```sh
curl -X POST http://127.0.0.1:8000/api/commands/storage-switch-usb
curl -X POST http://127.0.0.1:8000/api/commands/storage-switch-sd
```

The daemon stops preview and the shared DV source before switching so helper scripts can unmount `/data` safely. It refuses to switch while recording.

## USB-C mass-storage mode

USB-C transfer mode exports the block device currently backing `/data` to a host computer.

Start:

```sh
curl -X POST http://127.0.0.1:8000/api/commands/usb-storage-start
```

Stop:

```sh
curl -X POST http://127.0.0.1:8000/api/commands/usb-storage-stop
```

Before exporting, the daemon stops recording if needed, stops preview, stops the shared DV source, runs `sync`, and calls `/usr/sbin/equip1-usb-storage start`. While active, `state.mode` is `usb_transfer`, captures are hidden, and live streaming is disabled.

## Capture entries

`GET /api/captures` returns rows like:

```json
{
  "name": "capture_20260710_121314.dv",
  "path": "/data/captures/capture_20260710_121314.dv",
  "size_bytes": 12345678,
  "modified_at": 1783685594.0,
  "download_url": "/api/captures/capture_20260710_121314.dv/download",
  "thumbnail_url": "/api/captures/capture_20260710_121314.dv/thumbnail"
}
```

Only regular files with capture extensions are listed: `.dv`, `.avi`, `.mov`, `.mp4`, `.mkv`. Downloads and thumbnails are resolved by basename only to avoid path traversal.

## Thumbnails

After recording stops, the daemon first stamps the capture file mtime from embedded DV camera datecode when present. It checks the common DV pack layouts: VAUX video date/time (`0x62`/`0x63`), AAUX audio date/time (`0x52`/`0x53`), and a subcode fallback for video date/time packs. It then generates `capture_...jpg` beside the capture file using `ffmpeg`. It tries a few seek points and writes through a temporary file before replacing the final JPG. The web UI only surfaces capture cards whose thumbnails are ready, so a fresh recording appears complete.

## Capacity estimate

`storage.recording_minutes_available` uses a fixed estimate:

```text
216 MiB per minute of DV
```

This is conservative for DV25 and is used to block recording when less than one minute remains.
