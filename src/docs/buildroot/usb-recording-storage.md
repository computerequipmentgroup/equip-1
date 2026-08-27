# USB recording storage

Equip-1 records to `/data/captures`. On ROCK 2F, `/data` can be backed by a USB-A attached drive while the SD card remains the boot/rootfs media.

Boot behavior:

1. `/etc/init.d/S15data` waits briefly for USB storage.
2. If it finds an exFAT partition labelled `EQUIP1` on a non-root disk, it mounts that partition at `/data`.
3. If no `EQUIP1` USB partition exists but exactly one non-root exFAT partition exists, it mounts that partition.
4. If there is no unambiguous USB exFAT partition, it falls back to the SD/rootfs disk's recordings partition: the partition immediately after the rootfs partition.
5. If that SD recordings partition is missing on first boot, `S15data` creates it in the remaining free space, formats it as exFAT with label `EQUIP1`, and mounts it.
6. It creates `/data/captures` before `equip1d` starts.

This means the app does not need to change: recordings still go to `/data/captures`.

## Prepare a USB drive

Use one exFAT partition. Label `EQUIP1` is recommended but no longer required when only one USB exFAT partition is attached.

Linux example:

```sh
# WARNING: replace /dev/sdX1 with the USB drive partition, not the SD card.
sudo mkfs.exfat -n EQUIP1 /dev/sdX1
```

macOS example:

```sh
# WARNING: replace diskN with the USB drive from `diskutil list`.
diskutil eraseDisk ExFAT EQUIP1 MBR /dev/diskN
```

## Verify on the device

After booting with the USB drive attached:

```sh
mount | grep ' /data '
cat /data/equip1-boot-crumb.log | grep S15data
```

Expected log when a labelled USB drive is used:

```txt
S15data: using USB data partition /dev/sda1 label EQUIP1
```

Expected log when a single unlabelled USB exFAT drive is used:

```txt
S15data: using USB data partition /dev/sda1 without label
```

Expected fallback log without USB after provisioning exists:

```txt
S15data: no USB data partition found; falling back to SD /dev/mmcblk0p2
```

Expected first-boot provisioning log on an oversized ROCK 2F card flashed from a compressed image:

```txt
S15data: no USB data partition found and SD fallback partition is missing; attempting first-boot provisioning
S15data: creating SD recordings partition on /dev/mmcblk0 from sector ...s to end
S15data: formatting SD recordings partition /dev/mmcblk0p2 as exFAT label EQUIP1
S15data: using SD fallback data partition /dev/mmcblk0p2 label EQUIP1
```

## Runtime switching

`equip1d` watches for USB block devices while idle:

- inserting an unambiguous USB exFAT drive automatically switches `/data` to USB;
- removing the active USB drive automatically switches `/data` back to the SD fallback partition;
- no automatic switch is attempted while recording or while USB-C transfer mode is active.

Manual commands are still available:

```sh
curl -X POST http://127.0.0.1/api/commands/storage-switch-usb
curl -X POST http://127.0.0.1/api/commands/storage-switch-sd
```

Pressing select on the OLED `STORAGE` screen also asks for a USB switch. The helper refuses to switch while recording or while USB-C transfer mode is active. On failure it attempts to restore the previous `/data` mount or the SD fallback partition.

Set `EQUIP1_AUTO_STORAGE_SWITCH=0` to disable automatic switching.

## USB-C transfer mode

`equip1-usb-storage` exports the block device currently mounted at `/data`. If `/data` is mounted from the USB SSD, USB-C transfer mode exports that USB partition. If `/data` is mounted from SD fallback, it exports the SD recordings partition.

Do not enable transfer mode while recording; the script refuses if `dvgrab` is running. The daemon reports `state.mode = mounting` while switching `/data` or stopping/starting USB-C disk mode so the web and OLED UIs can show a wait indicator.

## Logs

Live logs are written under `/var/log/equip1/` so long-running services do not keep `/data` busy. A short-lived exporter mirrors snapshots to `/data/logs/` when `log_level` is not `quiet`:

- once after `/data` mounts at boot;
- periodically while the device is running;
- immediately before USB-C transfer mode attempts to unmount `/data`;
- after USB-C transfer mode stops and `/data` is mounted again.

This keeps logs visible when a user powers off and plugs the SD card into a computer, while still allowing `/data` to unmount for transfer mode.

## Operational notes

- DV capture is only about 3.5–4 MB/s, so USB 2.0 bandwidth is enough.
- Prefer a good SSD/enclosure or powered hub if the drive is unstable.
- Do not unplug the drive while recording.
- Hard power-off can still corrupt exFAT; stop recordings cleanly before removing power. `/data` is mounted asynchronously (`noatime`) because synchronous exFAT writes caused DV stream stalls on USB flash media.
- If multiple non-root `EQUIP1` partitions are attached, the first one reported by `blkid` is used and a warning is logged.
- If no `EQUIP1` partition is attached and multiple non-root exFAT partitions are present, Equip-1 refuses to guess and falls back to SD.
