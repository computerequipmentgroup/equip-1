from __future__ import annotations

import os
import select
import sys
import time
from dataclasses import dataclass

from .config import BoardConfig


@dataclass(frozen=True)
class ButtonEvents:
    up: bool = False
    select: bool = False
    down: bool = False


class Button:
    def __init__(self, chip: str, line: int):
        from periphery import GPIO

        self.gpio = GPIO(chip, line, "in")
        self.last_state = True
        self.last_press = 0.0

    def pressed(self) -> bool:
        current = self.gpio.read()
        now = time.time()
        if self.last_state and not current and (now - self.last_press) > 0.25:
            self.last_press = now
            self.last_state = current
            return True
        self.last_state = current
        return False

    def close(self) -> None:
        self.gpio.close()


class HardwareButtons:
    def __init__(self, board: BoardConfig):
        self.up = Button(board.gpiochip, board.btn_up)
        self.select = Button(board.gpiochip, board.btn_select)
        self.down = Button(board.gpiochip, board.btn_down)

    def poll(self) -> ButtonEvents:
        return ButtonEvents(
            up=self.up.pressed(),
            select=self.select.pressed(),
            down=self.down.pressed(),
        )

    def close(self) -> None:
        self.up.close()
        self.select.close()
        self.down.close()


class Buzzer:
    def __init__(self, board: BoardConfig):
        from periphery import GPIO

        self.gpio = GPIO(board.gpiochip, board.buzzer, "out")

    def beep(self, duration: float = 0.05, freq: int = 2048) -> None:
        cycles = int(duration * freq)
        half_period = 1.0 / freq / 2
        for _ in range(cycles):
            self.gpio.write(True)
            time.sleep(half_period)
            self.gpio.write(False)
            time.sleep(half_period)

    def close(self) -> None:
        self.gpio.close()


class NullBuzzer:
    def beep(self, duration: float = 0.05, freq: int = 2048) -> None:
        pass

    def close(self) -> None:
        pass


class KeyboardButtons:
    """Non-blocking stdin fallback: u=up, d=down, s=select."""

    def poll(self) -> ButtonEvents:
        if not select.select([sys.stdin], [], [], 0)[0]:
            return ButtonEvents()
        char = sys.stdin.read(1).lower()
        return ButtonEvents(up=char == "u", select=char == "s", down=char == "d")

    def close(self) -> None:
        pass


def make_buttons(board: BoardConfig):
    if os.environ.get("FIREHAT_OLED_MOCK") == "1":
        return KeyboardButtons()
    return HardwareButtons(board)


def make_buzzer(board: BoardConfig):
    if os.environ.get("FIREHAT_OLED_MOCK") == "1":
        return NullBuzzer()
    return Buzzer(board)
