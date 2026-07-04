from __future__ import annotations

import os
import time

from .api_client import FirehatApiClient
from .config import get_board_config
from .display import make_display
from .input import make_buttons, make_buzzer
from .leds import make_boot_leds
from .screens import BootScreen, DeckScreen, NetworkScreen, RecordingScreen, StorageScreen, SystemScreen, UsbTransferScreen


class OledApp:
    def __init__(self) -> None:
        self.board = get_board_config()
        api_base = os.environ.get("FIREHAT_API_BASE", "http://127.0.0.1:8000/api")
        api_timeout = float(os.environ.get("FIREHAT_API_TIMEOUT", "5.0"))
        self.api = FirehatApiClient(api_base, timeout=api_timeout)
        self.state_fetch_interval = float(os.environ.get("FIREHAT_STATE_FETCH_INTERVAL", "1.0"))
        self.display = make_display(self.board)
        self.buttons = make_buttons(self.board)
        self.buzzer = make_buzzer(self.board)
        self.leds = make_boot_leds()
        self.screens = [RecordingScreen(), NetworkScreen(), UsbTransferScreen(), DeckScreen(), StorageScreen()]
        self.boot_screen = BootScreen()
        self.boot_started_at = time.monotonic()
        self.boot_duration_seconds = float(os.environ.get("FIREHAT_BOOT_DURATION_SECONDS", "3.0"))
        self.boot_hold_seconds = float(os.environ.get("FIREHAT_BOOT_HOLD_SECONDS", "1.1"))
        self.frame_interval = float(os.environ.get("FIREHAT_OLED_FRAME_INTERVAL", str(1 / 30)))
        self.current_screen_idx = 0
        self.state: dict | None = None
        self._last_state_fetch = 0.0
        self._api_was_connected: bool | None = None
        self._boot_leds_cleared = False

    @property
    def current_screen(self):
        return self.screens[self.current_screen_idx]

    @property
    def is_booting(self) -> bool:
        return time.monotonic() - self.boot_started_at < self.boot_duration_seconds

    def _log_api_transition(self, connected: bool, detail: str | None = None) -> None:
        if self._api_was_connected is connected:
            return
        self._api_was_connected = connected
        if connected:
            print("OLED API connected", flush=True)
        else:
            print(f"OLED API offline: {detail or 'unknown error'}", flush=True)

    def _set_state(self, state: dict) -> None:
        self.state = state
        if state.get("mode") == "recording":
            self.current_screen_idx = 0

    def fetch_state_if_due(self, interval: float | None = None) -> None:
        interval = self.state_fetch_interval if interval is None else interval
        now = time.time()
        if now - self._last_state_fetch < interval:
            return
        self._last_state_fetch = now
        result = self.api.get_state()
        if result.ok and isinstance(result.data, dict):
            self._set_state(result.data)
            self._log_api_transition(True)
        else:
            detail = result.error or "invalid /api/state response"
            self._log_api_transition(False, detail)
            if self.state is None or not self.api.connected:
                self._set_state({
                    "mode": "offline",
                    "recording": {"active": False, "elapsed_seconds": 0},
                    "storage": {"recording_minutes_available": 0},
                    "network": {},
                    "error": {"message": "Daemon offline", "detail": detail},
                })

    def command(self, name: str) -> None:
        result = self.api.command(name)
        if result.ok and isinstance(result.data, dict) and "mode" in result.data:
            self._set_state(result.data)
        elif result.ok:
            self.fetch_state_if_due(interval=0)
        else:
            self._set_state({
                **(self.state or {}),
                "mode": "error",
                "error": {"message": "Command failed", "detail": result.error or name},
            })

    def navigate_up(self) -> None:
        if self.current_screen.on_up(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self.current_screen_idx = (self.current_screen_idx - 1) % len(self.screens)

    def navigate_down(self) -> None:
        if self.current_screen.on_down(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self.current_screen_idx = (self.current_screen_idx + 1) % len(self.screens)

    def poll_buttons(self) -> None:
        events = self.buttons.poll()
        if events.up:
            self.buzzer.beep()
            self.navigate_down()
        if events.down:
            self.buzzer.beep()
            self.navigate_up()
        if events.select:
            self.buzzer.beep()
            self.current_screen.on_select(self)

    def render(self) -> None:
        boot_elapsed = time.monotonic() - self.boot_started_at
        if self.is_booting:
            self.leds.boot_marquee(boot_elapsed)
        elif not self._boot_leds_cleared:
            self.leds.clear()
            self._boot_leds_cleared = True
        screen = self.boot_screen if self.is_booting else self.current_screen
        fallback_state = {"mode": "boot"} if self.is_booting else {"mode": "offline"}
        self.display.render(
            screen.render,
            {
                "state": self.state or fallback_state,
                "boot_elapsed": boot_elapsed,
                "boot_duration_seconds": self.boot_duration_seconds,
                "boot_hold_seconds": self.boot_hold_seconds,
            },
        )

    def run(self) -> None:
        try:
            while True:
                frame_started = time.monotonic()
                if not self.is_booting:
                    self.fetch_state_if_due()
                    self.poll_buttons()
                self.render()
                if self.frame_interval > 0:
                    time.sleep(max(0.0, self.frame_interval - (time.monotonic() - frame_started)))
        except KeyboardInterrupt:
            pass
        finally:
            self.display.clear()
            self.buttons.close()
            self.buzzer.close()
            self.leds.close()


def main() -> None:
    OledApp().run()


if __name__ == "__main__":
    main()
