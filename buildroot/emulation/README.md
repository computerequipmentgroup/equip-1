# Firehat Emulation Plan

Since the Firehat hardware isn't available during development, here's how to emulate each subsystem for testing.

## OLED Display (SH1106 over I2C)

Use `i2c-stub` kernel module to create a virtual I2C bus:

```bash
modprobe i2c-stub chip_addr=0x3C
```

The luma.oled library can then talk to the stub device. For visual output, set `LUMA_EMULATOR=1` to use luma.emulator's pygame-based display instead of real hardware.

## GPIO Buttons & Buzzer

Use `gpio-sim` (kernel 5.17+) to create virtual GPIO lines:

```bash
# Create a virtual GPIO chip with 32 lines
modprobe gpio-sim gpio_sim.num_banks=1 gpio_sim.label=firehat-emu
```

Alternatively, set `EQUIP_1_EMULATE=1` in environment and patch os.py to use mock GPIO:
- Buttons can be driven by keyboard input (stdin)
- Buzzer output redirected to console messages

## FireWire Device (/dev/fw1)

Create a mock device node:

```bash
# Simulate camera presence
mknod /dev/fw1 c 254 1
```

For actual capture testing, create a named pipe that feeds sample DV data:

```bash
mkfifo /tmp/dv-test-feed
# In another terminal, feed sample data:
cat sample.dv > /tmp/dv-test-feed
```

Mock `dvgrab` with a wrapper script that copies from the test feed.

## All-in-One Emulation Script

```bash
#!/bin/sh
# Start all emulation layers
export EQUIP_1_EMULATE=1
export EQUIP_1_BOARD_TYPE="rock2f"

# Virtual I2C for OLED
modprobe i2c-stub chip_addr=0x3C 2>/dev/null || true

# Mock FireWire device
[ ! -e /dev/fw1 ] && sudo mknod /dev/fw1 c 254 1

# Run with luma emulator for visual output
pip install luma.emulator 2>/dev/null
LUMA_EMULATOR=1 python3 /opt/equip1/os.py
```

## Testing Without Root

For development on a workstation without root:
1. Use `luma.emulator` for display (renders to a pygame window)
2. Replace `periphery.GPIO` with keyboard input via an emulation shim
3. Skip FireWire entirely — the app gracefully shows "NO CAM" when `/dev/fw1` is absent
