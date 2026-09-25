#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
fail() { echo "not ok - $1" >&2; exit 1; }

python3 - <<'PY' || exit 1
from uis.oled.config import get_board_config

rock2f = get_board_config("rock2f")
assert rock2f.buzzer == 19, rock2f
assert rock2f.buzzer_active_low is False, rock2f
assert rock2f.oled_address == 0x3C, rock2f
assert rock2f.oled_reset == 6, rock2f

rpi = get_board_config("rpi")
assert rpi.buzzer_active_low is True, rpi
PY

grep -q 'EQUIP1_BUZZER_ACTIVE_LOW ui buzzer_active_low 0' buildroot/overlay/etc/init.d/S61equip1-oled \
    || fail "OLED init must default Rock 2F buzzer to active-high/idle-low"

grep -q 'active_low = board.buzzer_active_low' uis/oled/input.py \
    || fail "Buzzer must use board-specific polarity"

grep -q 'EQUIP1_OLED_ADDRESS ui oled_address 0x3c' buildroot/overlay/etc/init.d/S61equip1-oled \
    || fail "OLED init must default Rock 2F OLED address to 0x3c"
grep -q 'EQUIP1_OLED_ADDRESSES ui oled_addresses "0x3c,0x3d"' buildroot/overlay/etc/init.d/S61equip1-oled \
    || fail "OLED init must try both common Rock 2F OLED addresses"
grep -q 'EQUIP1_OLED_RESET_LINE ui oled_reset_line 6' buildroot/overlay/etc/init.d/S61equip1-oled \
    || fail "OLED init must default Rock 2F OLED reset line to gpiochip4 line 6"

echo "ok - Rock 2F buzzer/OLED hardware defaults are correct"
