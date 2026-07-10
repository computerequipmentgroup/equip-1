# Buildroot and board bring-up notes

These notes were moved from `src/buildroot/docs/` so all source documentation lives under `src/docs/`.

- [equip1-app.md](equip1-app.md) — how app sources are staged into `/opt/equip1` and started by BusyBox init.
- [usb-recording-storage.md](usb-recording-storage.md) — `/data` storage selection, USB-A recording media, USB-C transfer mode, and logs.
- [enable-i2c-spi.md](enable-i2c-spi.md) — enabling ROCK 2F I2C/SPI overlays on development images.
- [enable-pwr-en.md](enable-pwr-en.md) — enabling a PCIe power regulator overlay on development images.

For the broader image flow, see [../buildroot-image.md](../buildroot-image.md).
