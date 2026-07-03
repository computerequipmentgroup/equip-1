from __future__ import annotations

import os
import time

from .api_client import FirehatApiClient
from .config import get_board_config
from .display import make_display
from .input import make_buttons, make_buzzer
from .screens import BootScreen, DeckScreen, NetworkScreen, RecordingScreen, StorageScreen, SystemScreen


class OledApp:
    def __init__(self) -> None:
        self.board = get_board_config()
        api_base = os.environ.get("FIREHAT_API_BASE", "http://127.0.0.1:8000/api")
        self.api = FirehatApiClient(api_base)
        self.display = make_display(self.board)
        self.buttons = make_buttons(self.board)
        self.buzzer = make_buzzer(self.board)
        self.screens = [RecordingScreen(), DeckScreen(), StorageScreen(), NetworkScreen(), SystemScreen()]
        self.boot_screen = BootScreen()
        self.boot_started_at = time.monotonic()
        self.boot_duration_seconds = 2.5
        self.current_screen_idx = 0
        self.state: dict | None = None
        self._last_state_fetch = 0.0

    @property
    def current_screen(self):
        return self.screens[self.current_screen_idx]

    @property
    def is_booting(self) -> bool:
        return time.monotonic() - self.boot_started_at < self.boot_duration_seconds

    def fetch_state_if_due(self, interval: float = 0.25) -> None:
        now = time.time()
        if now - self._last_state_fetch < interval:
            return
        self._last_state_fetch = now
        result = self.api.get_state()
        if result.ok and isinstance(result.data, dict):
            self.state = result.data
        elif self.state is None or not self.api.connected:
            self.state = {
                "mode": "offline",
                "recording": {"active": False, "elapsed_seconds": 0},
                "storage": {"recording_minutes_available": 0},
                "network": {},
                "error": {"message": "Daemon offline", "detail": result.error},
            }

    def command(self, name: str) -> None:
        result = self.api.command(name)
        if result.ok and isinstance(result.data, dict) and "mode" in result.data:
            self.state = result.data
        elif result.ok:
            self.fetch_state_if_due(interval=0)
        else:
            self.state = {
                **(self.state or {}),
                "mode": "error",
                "error": {"message": "Command failed", "detail": result.error or name},
            }

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
            self.navigate_up()
        if events.down:
            self.buzzer.beep()
            self.navigate_down()
        if events.select:
            self.buzzer.beep()
            self.current_screen.on_select(self)

    def render(self) -> None:
        boot_elapsed = time.monotonic() - self.boot_started_at
        screen = self.boot_screen if self.is_booting else self.current_screen
        fallback_state = {"mode": "boot"} if self.is_booting else {"mode": "offline"}
        self.display.render(
            screen.render,
            {
                "state": self.state or fallback_state,
                "boot_elapsed": boot_elapsed,
                "boot_duration_seconds": self.boot_duration_seconds,
            },
        )

    def run(self) -> None:
        try:
            while True:
                self.fetch_state_if_due()
                if not self.is_booting:
                    self.poll_buttons()
                self.render()
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.display.clear()
            self.buttons.close()
            self.buzzer.close()


def main() -> None:
    OledApp().run()


if __name__ == "__main__":
    main()
