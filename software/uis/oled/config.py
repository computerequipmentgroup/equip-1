from __future__ import annotations

import os
from dataclasses import dataclass


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


BOARDS: dict[str, BoardConfig] = {
    "rock2f": BoardConfig(
        name="rock2f",
        i2c_port=0,
        gpiochip="/dev/gpiochip4",
        buzzer=19,
        btn_up=15,
        btn_select=16,
        btn_down=22,
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
        return BOARDS[board]
    except KeyError as exc:
        valid = ", ".join(sorted(BOARDS))
        raise ValueError(f"Unknown board {board!r}. Expected one of: {valid}") from exc
