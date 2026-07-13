from __future__ import annotations

import os
import select
import sys
import time
from dataclasses import dataclass

from .config import BoardConfig


DEFAULT_BUTTON_DEBOUNCE_SECONDS = 0.025
DEFAULT_BUZZER_BEEP_SECONDS = 0.020


@dataclass(frozen=True)
class ButtonEvents:
    up: bool = False
    select: bool = False
    down: bool = False


class Button:
    def __init__(self, chip: str, line: int, debounce_seconds: float = DEFAULT_BUTTON_DEBOUNCE_SECONDS):
        from periphery import GPIO

        self.gpio = GPIO(chip, line, "in")
        self.debounce_seconds = max(0.0, debounce_seconds)
        self.last_state = True
        self.last_press = 0.0

    def pressed(self) -> bool:
        current = self.gpio.read()
        now = time.monotonic()
        if self.last_state and not current and (now - self.last_press) > self.debounce_seconds:
            self.last_press = now
            self.last_state = current
            return True
        self.last_state = current
        return False

    def close(self) -> None:
        self.gpio.close()


class HardwareButtons:
    def __init__(self, board: BoardConfig, debounce_seconds: float = DEFAULT_BUTTON_DEBOUNCE_SECONDS):
        self.up = Button(board.gpiochip, board.btn_up, debounce_seconds)
        self.select = Button(board.gpiochip, board.btn_select, debounce_seconds)
        self.down = Button(board.gpiochip, board.btn_down, debounce_seconds)

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
    def __init__(
        self,
        board: BoardConfig,
        beep_seconds: float = DEFAULT_BUZZER_BEEP_SECONDS,
        active_low: bool = True,
    ):
        from periphery import GPIO

        self.gpio = GPIO(board.gpiochip, board.buzzer, "out")
        self.beep_seconds = max(0.0, beep_seconds)
        self.active_value = not active_low
        self.idle_value = active_low
        self._silence()

    def _silence(self) -> None:
        self.gpio.write(self.idle_value)

    def beep(self, duration: float | None = None, freq: int = 2048) -> None:
        """Make one loud, bounded button-click pulse.

        The Firehat buzzer line is active-low, so the silent idle level is high.
        Always return to that idle level after the click so the buzzer cannot
        keep sounding between button presses. ``freq`` is kept for compatibility
        with older callers.
        """
        duration = self.beep_seconds if duration is None else max(0.0, duration)
        if duration <= 0:
            self._silence()
            return
        self.gpio.write(self.active_value)
        try:
            time.sleep(duration)
        finally:
            self._silence()

    def close(self) -> None:
        self._silence()
        self.gpio.close()


class NullBuzzer:
    def beep(self, duration: float | None = None, freq: int = 2048) -> None:
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


def make_buttons(board: BoardConfig, debounce_seconds: float = DEFAULT_BUTTON_DEBOUNCE_SECONDS):
    if os.environ.get("EQUIP1_OLED_MOCK") == "1":
        return KeyboardButtons()
    return HardwareButtons(board, debounce_seconds)


def make_buzzer(board: BoardConfig, beep_seconds: float = DEFAULT_BUZZER_BEEP_SECONDS):
    if os.environ.get("EQUIP1_OLED_MOCK") == "1":
        return NullBuzzer()
    return Buzzer(board, beep_seconds)
