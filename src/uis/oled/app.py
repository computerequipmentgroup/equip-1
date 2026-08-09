from __future__ import annotations

import threading
import time

from equip1d.logging import log, perf_enabled
from equip1d.settings import Equip1Settings, LIGHTS_BRIGHTNESS_DEFAULT

from .api_client import Equip1ApiClient
from .config import get_board_config
from .display import make_display
from .input import (
    DEFAULT_BUTTON_DEBOUNCE_SECONDS,
    DEFAULT_BUZZER_BEEP_SECONDS,
    ButtonEvents,
    make_buttons,
    make_buzzer,
)
from .leds import STANDARD_LED_SCALE, STATUS_MOUNTING, STATUS_NO_CAMERA, STATUS_READY, STATUS_RECORDING, Rgb, make_boot_leds
from .power import draw_battery_indicator
from .screens import BootScreen, GameScreen, NetworkScreen, RecordingScreen, SettingsScreen, StorageScreen, UsbTransferScreen


GAME_SCREEN_HOLD_SECONDS = 4.0


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
        button_debounce_ms = settings.get_float(
            "ui",
            "button_debounce_ms",
            DEFAULT_BUTTON_DEBOUNCE_SECONDS * 1000.0,
            env="EQUIP1_BUTTON_DEBOUNCE_MS",
        )
        button_beep_ms = settings.get_float(
            "ui",
            "button_beep_ms",
            DEFAULT_BUZZER_BEEP_SECONDS * 1000.0,
            env="EQUIP1_BUTTON_BEEP_MS",
        )
        self.display = make_display(self.board)
        log("OLED display initialized")
        self.buttons = make_buttons(self.board, debounce_seconds=button_debounce_ms / 1000.0)
        log(f"OLED buttons initialized; debounce={button_debounce_ms:g}ms")
        self.buzzer = make_buzzer(self.board, beep_seconds=button_beep_ms / 1000.0)
        self.leds = make_boot_leds()
        log("OLED LEDs initialized")
        self.screens = [RecordingScreen(), NetworkScreen(), UsbTransferScreen(), StorageScreen(), SettingsScreen()]
        self.game_screen = GameScreen()
        self.game_screen_active = False
        self._game_unlock_started_at: float | None = None
        self._game_unlock_triggered = False
        self.boot_screen = BootScreen()
        self.boot_started_at = time.monotonic()
        self.boot_duration_seconds = settings.get_float("ui", "boot_duration_seconds", 3.0, env="EQUIP1_BOOT_DURATION_SECONDS")
        self.boot_hold_seconds = settings.get_float("ui", "boot_hold_seconds", 1.1, env="EQUIP1_BOOT_HOLD_SECONDS")
        oled_fps = settings.get_float("ui", "oled_fps", 8.0, env="EQUIP1_OLED_FPS")
        self.frame_interval = 1.0 / oled_fps if oled_fps > 0 else 0.0
        self.current_screen_idx = 0
        self.state: dict | None = None
        self._last_state_fetch = 0.0
        self._api_was_connected: bool | None = None
        self._boot_leds_cleared = False
        self._api_lock = threading.Lock()
        self._command_thread: threading.Thread | None = None
        self._pending_command: str | None = None
        self._state_fetch_thread: threading.Thread | None = None
        self._stop_recording_requested_at: float | None = None

    @property
    def current_screen(self):
        return self.game_screen if self.game_screen_active else self.screens[self.current_screen_idx]

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
        if state.get("mode") == "recording":
            self.game_screen_active = False
            self.current_screen_idx = 0
        else:
            self._stop_recording_requested_at = None

    def _recording_active(self) -> bool:
        return (self.state or {}).get("mode") == "recording"

    @property
    def stop_recording_pending(self) -> bool:
        return self._stop_recording_requested_at is not None and (self.state or {}).get("mode") == "recording"

    def fetch_state_if_due(self, interval: float | None = None) -> None:
        interval = self.state_fetch_interval if interval is None else interval
        now = time.time()
        if now - self._last_state_fetch < interval:
            return
        self._last_state_fetch = now
        self._fetch_state()

    def fetch_state_in_background_if_due(self, interval: float | None = None) -> None:
        interval = self.state_fetch_interval if interval is None else interval
        now = time.time()
        if now - self._last_state_fetch < interval:
            return
        if self._pending_command is not None:
            return
        if self._state_fetch_thread is not None and self._state_fetch_thread.is_alive():
            return
        self._last_state_fetch = now
        thread = threading.Thread(target=self._fetch_state, name="oled-state-fetch", daemon=True)
        self._state_fetch_thread = thread
        thread.start()

    def _fetch_state(self) -> None:
        started = time.monotonic()
        with self._api_lock:
            result = self.api.get_state()
        self._perf_log("oled.api_state", started)
        if self._pending_command is not None:
            return
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
        self._run_command(name)

    def command_async(self, name: str) -> bool:
        if self._command_thread is not None and self._command_thread.is_alive():
            return False
        if name == "stop-recording":
            self._stop_recording_requested_at = time.monotonic()
        self._pending_command = name
        thread = threading.Thread(target=self._command_worker, args=(name,), name=f"oled-command-{name}", daemon=True)
        self._command_thread = thread
        thread.start()
        return True

    def _command_worker(self, name: str) -> None:
        try:
            self._run_command(name)
        finally:
            self._pending_command = None

    def _run_command(self, name: str) -> None:
        started = time.monotonic()
        with self._api_lock:
            result = self.api.command(name)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if result.ok and isinstance(result.data, dict) and "mode" in result.data:
            log(f"OLED command {name} ok mode={result.data.get('mode')} {elapsed_ms:.1f}ms", level="debug")
            self._set_state(result.data)
        elif result.ok:
            log(f"OLED command {name} ok; refreshing state {elapsed_ms:.1f}ms", level="debug")
            self.fetch_state_if_due(interval=0)
        elif name == "stop-recording" and self._recover_stop_command_failure(result.error or name):
            log(f"OLED command {name} failed but stop state recovered: {result.error or name}", level="warning")
        else:
            detail = result.error or name
            log(f"OLED command {name} failed: {detail}", level="warning")
            self._set_state({
                **(self.state or {}),
                "mode": "error",
                "error": {"message": "Command failed", "detail": detail},
            })

    def set_setting(self, path: str, payload: dict) -> None:
        started = time.monotonic()
        with self._api_lock:
            result = self.api.post_json(path, payload)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if result.ok and isinstance(result.data, dict):
            log(f"OLED setting {path} ok {elapsed_ms:.1f}ms", level="debug")
            self._set_state(result.data)
        else:
            detail = result.error or path
            log(f"OLED setting {path} failed: {detail}", level="warning")
            self._set_state({
                **(self.state or {}),
                "mode": "error",
                "error": {"message": "Setting failed", "detail": detail},
            })

    def _recover_stop_command_failure(self, detail: str) -> bool:
        # Stop is safety/UX critical: a transient OLED HTTP timeout should not
        # leave the local UI stuck in error if the daemon has already left
        # recording (or can report current state). Check once synchronously in
        # the command worker before surfacing a command error.
        started = time.monotonic()
        with self._api_lock:
            state_result = self.api.get_state()
        self._perf_log("oled.api_state_after_stop_error", started)
        if state_result.ok and isinstance(state_result.data, dict):
            self._set_state(state_result.data)
            self._log_api_transition(True)
            return state_result.data.get("mode") != "recording"
        self._log_api_transition(False, state_result.error or detail)
        return False

    def _enter_game_screen(self) -> None:
        if self.game_screen_active:
            return
        self.game_screen_active = True
        self.game_screen.on_enter(self)

    def _change_screen(self, delta: int) -> None:
        if self.game_screen_active:
            self.game_screen_active = False
        else:
            self.current_screen_idx = (self.current_screen_idx + delta) % len(self.screens)
        on_enter = getattr(self.current_screen, "on_enter", None)
        if on_enter is not None:
            on_enter(self)

    def navigate_up(self) -> None:
        if self._recording_active():
            return
        if self.current_screen.on_up(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(-1)

    def navigate_down(self) -> None:
        if self._recording_active():
            return
        if self.current_screen.on_down(self):
            return
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(1)

    def next_screen(self) -> None:
        """Advance to the next screen regardless of the up/down button handlers;
        used by screens (like the flipper game) that consume up/down themselves."""
        if self._recording_active():
            return
        if self.current_screen.can_navigate(self.state or {}):
            self._change_screen(1)

    def poll_buttons(self) -> None:
        events = self.buttons.poll()
        if self._poll_game_unlock(events):
            return
        if events.up:
            self.buzzer.beep()
            self.navigate_down()
        if events.down:
            self.buzzer.beep()
            self.navigate_up()
        if events.select:
            self.buzzer.beep()
            self.current_screen.on_select(self)

    def _poll_game_unlock(self, events: ButtonEvents) -> bool:
        if not events.all_held:
            self._game_unlock_started_at = None
            self._game_unlock_triggered = False
            return False
        if self._recording_active():
            return True

        now = time.monotonic()
        if self._game_unlock_started_at is None:
            self._game_unlock_started_at = now
        if not self._game_unlock_triggered and now - self._game_unlock_started_at >= GAME_SCREEN_HOLD_SECONDS:
            self._enter_game_screen()
            self._game_unlock_triggered = True
            self.buzzer.beep()
        return True

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
        conversion = (self.state or {}).get("conversion") or {}
        if mode == "mounting" or mode == "converting" or conversion.get("active"):
            return self._dim_led(STATUS_MOUNTING)
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

        def render_screen(draw, width: int, height: int, context: dict) -> None:
            screen.render(draw, width, height, context)
            if not self.is_booting:
                draw_battery_indicator(draw, width, height, context)

        self.display.render(
            render_screen,
            {
                "state": self.state or fallback_state,
                "boot_elapsed": boot_elapsed,
                "boot_duration_seconds": self.boot_duration_seconds,
                "boot_hold_seconds": self.boot_hold_seconds,
                "stop_recording_pending": self.stop_recording_pending,
            },
        )
        self._perf_log("oled.render_total", started)

    def run(self) -> None:
        log("OLED run loop starting")
        try:
            while True:
                frame_started = time.monotonic()
                if not self.is_booting:
                    self.fetch_state_in_background_if_due()
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
