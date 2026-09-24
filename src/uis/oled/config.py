from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class BoardConfig:
    name: str
    i2c_port: int
    gpiochip: str
    buzzer: int
    btn_up: int
    btn_select: int
    btn_down: int
    oled_address: int = 0x3C
    oled_driver: str = "sh1106"
    oled_reset: int | None = None


BOARDS: dict[str, BoardConfig] = {
    "rock2f": BoardConfig(
        name="rock2f",
        i2c_port=0,
        gpiochip="/dev/gpiochip4",
        buzzer=19,
        btn_up=15,
        btn_select=16,
        btn_down=22,
        oled_driver="ssd1306",
        oled_reset=6,
    ),
    "rpi": BoardConfig(
        name="rpi",
        i2c_port=1,
        gpiochip="/dev/gpiochip4",
        buzzer=12,
        btn_up=22,
        btn_select=27,
        btn_down=17,
    ),
}


def get_board_config(name: str | None = None) -> BoardConfig:
    board = name or os.environ.get("EQUIP_1_BOARD_TYPE", "rock2f")
    try:
        config = BOARDS[board]
    except KeyError as exc:
        valid = ", ".join(sorted(BOARDS))
        raise ValueError(f"Unknown board {board!r}. Expected one of: {valid}") from exc

    oled_driver = os.environ.get("EQUIP1_OLED_DRIVER")
    oled_reset = os.environ.get("EQUIP1_OLED_RESET_LINE")
    if oled_driver or oled_reset is not None:
        reset_line = None if oled_reset == "" else int(oled_reset) if oled_reset is not None else config.oled_reset
        config = replace(
            config,
            oled_driver=oled_driver or config.oled_driver,
            oled_reset=reset_line,
        )
    return config
