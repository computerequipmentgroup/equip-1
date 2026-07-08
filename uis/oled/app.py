from __future__ import annotations

import time

from equip1d.logging_config import log, perf_enabled
from equip1d.settings import Equip1Settings, LIGHTS_BRIGHTNESS_DEFAULT

from .api_client import Equip1ApiClient
from .config import get_board_config
from .display import make_display
from .input import make_buttons, make_buzzer
from .leds import STANDARD_LED_SCALE, STATUS_NO_CAMERA, STATUS_READY, STATUS_RECORDING, Rgb, make_boot_leds
from .screens import BootScreen, GameScreen, NetworkScreen, RecordingScreen, StorageScreen, UsbTransferScreen


class OledApp:
    def __init__(self) -> None:
        log("OLED app starting")
        self.board = get_board_config()
        log(f"OLED board config: {self.board.name}")
        settings = Equip1Settings()
        api_base = settings.get("ui", "api_base", "http://127.0.0.1:8000/api", env="EQUIP1_API_BASE") or "http://127.0.0.1:8000/api"
        api_timeout = settings.get_float("ui", "api_timeout", 5.0, env="EQUIP1_API_TIMEOUT")
        self.api = Equip1ApiClient(api_base, timeout=api_timeout)
        self.state_fetch_interval = settings.get_float("ui", "state_fetch_interval", 1.0, env="EQUIP1_STATE_FETCH_INTERVAL")
        self.display = make_display(self.board)
        log("OLED display initialized")
        self.buttons = make_buttons(self.board)
        log("OLED buttons initialized")
        self.buzzer = make_buzzer(self.board)
        self.leds = make_boot_leds()
        log("OLED LEDs initialized")
        self.screens = [RecordingScreen(), NetworkScreen(), UsbTransferScreen(), StorageScreen(), GameScreen()]
        self.boot_screen = BootScreen()
        self.boot_started_at = time.monotonic()
        self.boot_duration_seconds = settings.get_float("ui", "boot_duration_seconds", 3.0, env="EQUIP1_BOOT_DURATION_SECONDS")
        self.boot_hold_seconds = settings.get_float("ui", "boot_hold_seconds", 1.1, env="EQUIP1_BOOT_HOLD_SECONDS")
        oled_fps = settings.get_float("ui", "oled_fps", 30.0, env="EQUIP1_OLED_FPS")
        self.frame_interval = 1.0 / oled_fps if oled_fps > 0 else 0.0
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
            log("OLED API connected")
        else:
            log(f"OLED API offline: {detail or 'unknown error'}", level="warning")

    def _perf_enabled(self) -> bool:
        return perf_enabled()

    def _perf_log(self, name: str, started: float, threshold_ms: float = 10.0) -> None:
        if not self._perf_enabled():
            return
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if elapsed_ms >= threshold_ms:
            print(f"[PERF] {name} {elapsed_ms:.1f}ms", flush=True)

    def _set_state(self, state: dict) -> None:
        self.state = state

    def fetch_state_if_due(self, interval: float | None = None) -> None:
        interval = self.state_fetch_interval if interval is None else interval
        now = time.time()
        if now - self._last_state_fetch < interval:
            return
        self._last_state_fetch = now
        started = time.monotonic()
        result = self.api.get_state()
        self._perf_log("oled.api_state", started)
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
                    "storage": {"recording_minutes_available": 0, "device_kind": "unknown"},
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

    def _change_screen(self, delta: int) -> None:
        self.current_screen_idx = (self.current_screen_idx + delta) % len(self.screens)
        on_enter = getattr(self.current_screen, "on_enter", None)
        if on_enter is not None:
            on_enter(self)

    def navigate_up(self) -> None:
        if self.current_screen.on_up(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(-1)

    def navigate_down(self) -> None:
        if self.current_screen.on_down(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(1)

    def next_screen(self) -> None:
        """Advance to the next screen regardless of the up/down button handlers;
        used by screens (like the flipper game) that consume up/down themselves."""
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(1)

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

    def _lights_enabled(self) -> bool:
        lights = (self.state or {}).get("lights") or {}
        return bool(lights.get("enabled", True))

    def _lights_brightness(self) -> float:
        lights = (self.state or {}).get("lights") or {}
        try:
            return max(0.0, min(1.0, float(lights.get("brightness", LIGHTS_BRIGHTNESS_DEFAULT))))
        except (TypeError, ValueError):
            return LIGHTS_BRIGHTNESS_DEFAULT

    def _dim_led(self, color: Rgb) -> Rgb:
        return color.scaled(self._lights_brightness())

    def _standard_led_colors(self):
        """The user-configurable per-LED standard colors, each scaled by the
        runtime brightness slider. Falls back to no-camera blue for any LED the
        daemon has not reported (e.g. while offline)."""
        lights = (self.state or {}).get("lights") or {}
        colors = lights.get("default_colors")
        scale = STANDARD_LED_SCALE * self._lights_brightness()
        result = []
        if isinstance(colors, (list, tuple)):
            for color in colors:
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    try:
                        result.append(Rgb(int(color[0]), int(color[1]), int(color[2])).scaled(scale))
                        continue
                    except (TypeError, ValueError):
                        pass
                result.append(self._dim_led(STATUS_NO_CAMERA))
        if not result:
            result = [self._dim_led(STATUS_NO_CAMERA)]
        return result

    def _status_led_color(self):
        """The uniform status color for the current state, or None to fall back
        to the per-LED standard colors. Recording is the most important state;
        screen-specific led_override() output takes precedence over this in
        render()."""
        mode = (self.state or {}).get("mode")
        if mode == "recording":
            return self._dim_led(STATUS_RECORDING)
        # On the record screen, show ready-green whenever a camera is attached;
        # otherwise fall back to the standard colors. Every other screen shows
        # the standard colors, so the LEDs are never fully off.
        if isinstance(self.current_screen, RecordingScreen):
            camera = (self.state or {}).get("camera") or {}
            if camera.get("connected"):
                return self._dim_led(STATUS_READY)
        return None

    def render(self) -> None:
        started = time.monotonic()
        boot_elapsed = time.monotonic() - self.boot_started_at
        if self.is_booting:
            self.leds.boot_marquee(boot_elapsed)
        else:
            if not self._boot_leds_cleared:
                self.leds.clear()
                self._boot_leds_cleared = True
            if not self._lights_enabled():
                self.leds.set_status(None)
            else:
                override = self.current_screen.led_override(self)
                if override is not None:
                    self.leds.set_all(override)
                else:
                    status = self._status_led_color()
                    if status is not None:
                        self.leds.set_status(status)
                    else:
                        self.leds.set_status_colors(self._standard_led_colors())
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
        self._perf_log("oled.render_total", started)

    def run(self) -> None:
        log("OLED run loop starting")
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
