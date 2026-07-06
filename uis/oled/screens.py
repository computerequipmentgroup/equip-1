from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any

from .formatting import bytes_gb, hhmmss, percent
from .leds import Rgb


HEADER_Y = 0
CONTENT_Y = 20
LINE_HEIGHT = 16


class Screen:
    title = ""

    def on_select(self, app) -> None:
        pass

    def on_up(self, app) -> bool:
        return False

    def on_down(self, app) -> bool:
        return False

    def can_navigate(self, state: dict[str, Any]) -> bool:
        return True

    def led_override(self, app) -> "Rgb | None":
        """Return a color to drive every LED while this screen is active, or
        None to fall back to the default status-LED behavior."""
        return None

    def render(self, draw, width: int, height: int, context: dict) -> None:
        raise NotImplementedError


def _font(context: dict, name: str):
    return getattr(context["fonts"], name)


def _center(draw, width: int, y: int, text: str, font, fill: int = 255) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, y), text, font=font, fill=fill)


def _right(draw, width: int, y: int, text: str, font, fill: int = 255) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((width - (bbox[2] - bbox[0]), y), text, font=font, fill=fill)


class BootScreen(Screen):
    title = "BOOT"

    def __init__(self) -> None:
        # The morph target and the text-pixel layout are constant for the whole
        # boot animation, so cache them instead of recomputing every frame.
        self._target_cache: tuple[tuple[int, int, str], list[tuple[int, int]]] | None = None
        self._text_cache: tuple[tuple[int, int], list[tuple[int, int, int]]] | None = None

    def can_navigate(self, state: dict[str, Any]) -> bool:
        return False

    def _target_pixels(self, width: int, height: int, context: dict, mode: str) -> list[tuple[int, int]]:
        key = (width, height, mode)
        if self._target_cache is not None and self._target_cache[0] == key:
            return self._target_cache[1]

        from PIL import Image, ImageDraw

        from .display import OledDraw

        target = Image.new("1", (width, height))
        target_state = context.get("state") or {}
        if mode == "boot":
            target_state = {"mode": "idle", "recording": {"active": False, "elapsed_seconds": 0}, "storage": {"recording_minutes_available": 0}}
        RecordingScreen().render(OledDraw(target, ImageDraw.Draw(target)), width, height, {**context, "state": target_state})
        pixels = list(target.getdata())
        lit = [(i % width, i // width) for i, value in enumerate(pixels) if value]
        self._target_cache = (key, lit)
        return lit

    def _text_pixels(self, width: int, height: int, text_positions, image) -> list[tuple[int, int, int]]:
        key = (width, height)
        if self._text_cache is not None and self._text_cache[0] == key:
            return self._text_cache[1]
        candidates: list[tuple[int, int, int]] = []
        for x, y, bbox in text_positions:
            for py in range(max(0, y + bbox[1]), min(height, y + bbox[3])):
                for px in range(max(0, x + bbox[0]), min(width, x + bbox[2])):
                    if image is not None and not image.getpixel((px, py)):
                        continue
                    seed = (px * 1103515245 + py * 12345 + 97) & 0x7FFFFFFF
                    candidates.append((px, py, seed))
        self._text_cache = (key, candidates)
        return candidates

    def render(self, draw, width: int, height: int, context: dict) -> None:
        elapsed = float(context.get("boot_elapsed", time.monotonic() % 3.0))
        duration = max(0.1, float(context.get("boot_duration_seconds", 3.0)))
        hold = max(0.0, float(context.get("boot_hold_seconds", 1.1)))

        font = _font(context, "font_boot")
        lines = ("equip-1", "firehat")
        line_gap = 2
        line_layout = []
        total_text_height = line_gap * (len(lines) - 1)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_height = bbox[3] - bbox[1]
            total_text_height += text_height
            line_layout.append((line, bbox, text_height))

        y_cursor = (height - total_text_height) // 2
        text_positions = []
        for line, bbox, text_height in line_layout:
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2 - bbox[0]
            y = y_cursor - bbox[1]
            draw.text((x, y), line, font=font, fill=255)
            text_positions.append((x, y, bbox))
            y_cursor += text_height + line_gap

        fade_start = min(hold, duration - 0.1)
        if elapsed <= fade_start:
            return

        fade = max(0.0, min(1.0, (elapsed - fade_start) / max(0.1, duration - fade_start)))
        fade_eased = fade * fade * (3.0 - 2.0 * fade)
        threshold = int(fade_eased * 256)

        target_mode = (context.get("state") or {}).get("mode") or "boot"
        target_pixels = self._target_pixels(width, height, context, target_mode)

        image = getattr(draw, "image", None)
        candidates = self._text_pixels(width, height, text_positions, image)

        drift = min(1.0, fade_eased * 1.08)
        morph_visibility = int((1.0 - max(0.0, min(1.0, (fade - 0.78) / 0.22))) * 256)
        for px, py, seed in candidates:
            if seed % 256 >= threshold:
                continue
            draw.point((px, py), fill=0)
            if not target_pixels or ((seed >> 8) % 256) >= morph_visibility:
                continue
            tx, ty = target_pixels[seed % len(target_pixels)]
            mx = int(px + (tx - px) * drift)
            my = int(py + (ty - py) * drift)
            draw.point((mx, my), fill=255)

        target_threshold = int(max(0.0, min(1.0, (fade - 0.25) / 0.75)) * 256)
        for tx, ty in target_pixels:
            seed = (tx * 1103515245 + ty * 12345 + 193) & 0x7FFFFFFF
            if seed % 256 < target_threshold:
                draw.point((tx, ty), fill=255)


class RecordingScreen(Screen):
    title = "RECORD"

    def on_select(self, app) -> None:
        state = app.state or {}
        if state.get("mode") == "recording":
            app.command("stop-recording")
        elif state.get("mode") in {"idle", "no_camera", "storage_full", "error"}:
            if state.get("mode") == "error":
                app.command("clear-error")
            else:
                app.command("start-recording")

    def can_navigate(self, state: dict[str, Any]) -> bool:
        return state.get("mode") != "recording"

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        mode = state.get("mode", "offline")
        recording = state.get("recording") or {}
        storage = state.get("storage") or {}
        minutes_available = int(storage.get("recording_minutes_available", 0) or 0)
        minutes_label = f"{minutes_available:03d}m"
        font_medium = _font(context, "font_medium")
        font_big = _font(context, "font_big")

        if mode == "recording":
            rec_x = 0
            rec_y = 0
            draw.text((rec_x, rec_y), "REC", font=font_medium, fill=255)
            rec_bbox = draw.textbbox((rec_x, rec_y), "REC", font=font_medium)
            dot_size = max(6, (rec_bbox[3] - rec_bbox[1]) - 4)
            dot_x = rec_bbox[2] + 4
            dot_y = rec_bbox[1] + ((rec_bbox[3] - rec_bbox[1]) - dot_size) // 2
            if int(time.time() * 2) % 2:
                draw.ellipse((dot_x, dot_y, dot_x + dot_size - 1, dot_y + dot_size - 1), fill=255)
            _right(draw, width, HEADER_Y, minutes_label, font_medium)
            _center(draw, width, CONTENT_Y, hhmmss(recording.get("elapsed_seconds")), font_big)
            return

        draw.text((0, HEADER_Y), "RECORD", font=font_medium, fill=255)
        _right(draw, width, HEADER_Y, minutes_label, font_medium)

        if mode == "offline":
            _center(draw, width, CONTENT_Y, "DAEMON", font_big)
            _center(draw, width, CONTENT_Y + 30, "offline", font_medium)
        elif mode == "no_camera":
            _center(draw, width, CONTENT_Y, "NO CAM", font_big)
        elif mode == "storage_full":
            _center(draw, width, CONTENT_Y, "FULL", font_big)
            _center(draw, width, CONTENT_Y + 30, "storage", font_medium)
        elif mode == "error":
            _center(draw, width, CONTENT_Y, "ERROR", font_big)
            _center(draw, width, CONTENT_Y + 30, "press clear", font_medium)
        elif mode == "usb_transfer":
            _center(draw, width, CONTENT_Y, "USB", font_big)
            _center(draw, width, CONTENT_Y + 30, "transfer mode", font_medium)
        else:
            _center(draw, width, CONTENT_Y, "00:00:00", font_big)


class StorageScreen(Screen):
    title = "STORAGE"

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        storage = state.get("storage") or {}
        font = _font(context, "font_medium")
        total = storage.get("total_bytes")
        used = storage.get("used_bytes")
        free = storage.get("free_bytes")
        draw.text((0, HEADER_Y), "STORAGE", font=font, fill=255)
        draw.text((0, CONTENT_Y), f"Free: {bytes_gb(free)}", font=font, fill=255)
        draw.text((0, CONTENT_Y + LINE_HEIGHT), f"Used: {percent(used, total)}%", font=font, fill=255)
        draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), f"Time: {storage.get('recording_minutes_available', 0)}m", font=font, fill=255)


def _wifi_qr_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:").replace('"', '\\"')


def _wifi_qr_payload(ssid: str, password: str) -> str:
    return f"WIFI:T:WPA;S:{_wifi_qr_escape(ssid)};P:{_wifi_qr_escape(password)};;"


def _qr_image(payload: str, max_size: int):
    from PIL import Image
    import qrcode

    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    # OLED pixels are visible when they are white/lit.  Render the QR modules
    # as lit pixels on the black OLED background; normal black-on-white QR
    # polarity looks like sparse dots/holes on this display.
    image = qr.make_image(fill_color="white", back_color="black").convert("1")
    scale = max(1, max_size // max(image.size))
    scaled_size = (image.width * scale, image.height * scale)
    if scaled_size != image.size and max(scaled_size) <= max_size:
        image = image.resize(scaled_size, Image.Resampling.NEAREST)
    if image.size != (max_size, max_size):
        canvas = Image.new("1", (max_size, max_size), 0)
        canvas.paste(image, ((max_size - image.width) // 2, (max_size - image.height) // 2))
        image = canvas
    return image


def _wifi_qr_image(ssid: str, password: str, max_size: int):
    return _qr_image(_wifi_qr_payload(ssid, password), max_size)


def _url_qr_image(url: str, max_size: int):
    return _qr_image(url, max_size)


class NetworkScreen(Screen):
    title = "NETWORK"

    def __init__(self) -> None:
        self.qr_mode: str | None = None
        self._qr_key: tuple[str, str] | None = None
        self._qr_image = None

    def _available_qr_modes(self, network: dict) -> list[str]:
        modes = []
        if network.get("ssid") and network.get("password"):
            modes.append("wifi")
        if network.get("url"):
            modes.append("url")
        return modes

    def on_select(self, app) -> None:
        network = (app.state or {}).get("network") or {}
        modes = self._available_qr_modes(network)
        if not modes:
            self.qr_mode = None
            return
        if self.qr_mode not in modes:
            self.qr_mode = modes[0]
            return
        idx = modes.index(self.qr_mode)
        self.qr_mode = modes[idx + 1] if idx + 1 < len(modes) else None

    def on_up(self, app) -> bool:
        if self.qr_mode:
            self.qr_mode = None
            return True
        return False

    def on_down(self, app) -> bool:
        if self.qr_mode:
            self.qr_mode = None
            return True
        return False

    def _render_qr(self, draw, width: int, height: int, label: str, key: tuple[str, str], payload: str, font) -> None:
        try:
            qr_max_size = min(width, height)
            if self._qr_key != key or self._qr_image is None:
                self._qr_image = _qr_image(payload, qr_max_size)
                self._qr_key = key
            x = (width - self._qr_image.width) // 2
            y = (height - self._qr_image.height) // 2
            draw.image.paste(self._qr_image, (x, y))
            draw.rectangle((0, 0, 20, LINE_HEIGHT - 1), fill=0)
            draw.text((0, 0), label, font=font, fill=255)
        except Exception:
            draw.text((0, HEADER_Y), "NETWORK", font=font, fill=255)
            draw.text((0, CONTENT_Y), "QR unavailable", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Check qrcode dep", font=font, fill=255)

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        network = state.get("network") or {}
        font = _font(context, "font_medium")
        ssid = network.get("ssid")
        password = network.get("password")
        url = network.get("url")
        if self.qr_mode == "wifi" and ssid and password:
            self._render_qr(draw, width, height, "AP", ("wifi", str(ssid), str(password)), _wifi_qr_payload(str(ssid), str(password)), font)
            return
        if self.qr_mode == "url" and url:
            self._render_qr(draw, width, height, "URL", ("url", str(url)), str(url), font)
            return

        self.qr_mode = None
        draw.text((0, HEADER_Y), "NETWORK", font=font, fill=255)
        if ssid:
            draw.text((0, CONTENT_Y), f"WiFi: {ssid}"[:21], font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), f"Pass: {password or 'unknown'}"[:21], font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), (network.get("url") or "Starting AP")[:21], font=font, fill=255)
        else:
            host = network.get("hostname") or "firehat"
            draw.text((0, CONTENT_Y), network.get("url") or f"http://{host}.local", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), network.get("ip") or "No connection", font=font, fill=255)


class DeckScreen(Screen):
    title = "DECK"

    def __init__(self) -> None:
        self.options = [
            ("Back", None),
            ("Play", "deck-play"),
            ("Stop", "deck-stop"),
            ("Rewind", "deck-rewind"),
            ("Fast fwd", "deck-fast-forward"),
        ]
        self.selected = 0
        self.controlling = False

    def on_select(self, app) -> None:
        state = app.state or {}
        camera = state.get("camera") or {}
        if not camera.get("connected"):
            app.command("rescan-camera")
            return
        if not self.controlling:
            self.controlling = True
            return
        _, command = self.options[self.selected]
        if command is None:
            self.controlling = False
            self.selected = 0
            return
        app.command(command)
        self.controlling = False
        self.selected = 0

    def on_up(self, app) -> bool:
        if not self.controlling:
            return False
        self.selected = (self.selected - 1) % len(self.options)
        return True

    def on_down(self, app) -> bool:
        if not self.controlling:
            return False
        self.selected = (self.selected + 1) % len(self.options)
        return True

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        camera = state.get("camera") or {}
        deck = state.get("deck") or {}
        font = _font(context, "font_medium")
        status = str(deck.get("status") or "unknown")[:12]
        draw.text((0, HEADER_Y), "DECK", font=font, fill=255)
        _right(draw, width, HEADER_Y, status, font, fill=255)
        if not camera.get("connected"):
            draw.text((0, CONTENT_Y), "No camera", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Press rescan", font=font, fill=255)
            return
        if not self.controlling:
            draw.text((0, CONTENT_Y), str(deck.get("timecode") or "--:--:--:--")[:20], font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Press controls", font=font, fill=255)
            return
        start = max(0, min(self.selected - 1, len(self.options) - 3))
        for row, option_index in enumerate(range(start, min(start + 3, len(self.options)))):
            label, _ = self.options[option_index]
            prefix = "> " if option_index == self.selected else "  "
            draw.text((0, CONTENT_Y + row * LINE_HEIGHT), prefix + label, font=font, fill=255)


class ErrorScreen(Screen):
    title = "ERROR"

    def on_select(self, app) -> None:
        app.command("clear-error")

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        error = state.get("error") or {}
        font = _font(context, "font_medium")
        draw.text((0, HEADER_Y), "ERROR", font=font, fill=255)
        draw.text((0, CONTENT_Y), str(error.get("message") or "Unknown")[:20], font=font, fill=255)
        detail = str(error.get("detail") or "Press to clear")
        draw.text((0, CONTENT_Y + LINE_HEIGHT), detail[:20], font=font, fill=255)
        draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), "Press to clear", font=font, fill=255)


class UsbTransferScreen(Screen):
    title = "TRANSFER"

    def on_select(self, app) -> None:
        state = app.state or {}
        if state.get("mode") == "usb_transfer":
            app.command("usb-storage-stop")
        elif state.get("mode") != "recording":
            app.command("usb-storage-start")

    def can_navigate(self, state: dict[str, Any]) -> bool:
        return state.get("mode") != "recording"

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        mode = state.get("mode", "offline")
        font = _font(context, "font_medium")
        draw.text((0, HEADER_Y), "TRANSFER", font=font, fill=255)
        if mode == "usb_transfer":
            draw.text((0, CONTENT_Y), "Disk active", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Eject on PC", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), "Press stop", font=font, fill=255)
        elif mode == "recording":
            draw.text((0, CONTENT_Y), "Stop recording", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "before USB", font=font, fill=255)
        elif mode == "offline":
            draw.text((0, CONTENT_Y), "Daemon offline", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "USB unavailable", font=font, fill=255)
        elif mode == "error":
            error = state.get("error") or {}
            detail = str(error.get("detail") or error.get("message") or "Command failed")
            draw.text((0, CONTENT_Y), "USB failed", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), detail[:20], font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), "See SD log", font=font, fill=255)
        else:
            draw.text((0, CONTENT_Y), "Native file copy", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Press to expose", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT * 2), "EQUIP1 disk", font=font, fill=255)


class SystemScreen(Screen):
    title = "SYSTEM"

    def __init__(self) -> None:
        self.selected = 0
        self.confirming = False

    def _options(self, state: dict[str, Any]) -> list[str]:
        if state.get("mode") == "usb_transfer":
            return ["USB Stop", "Cancel"]
        return ["USB Disk", "Shutdown", "Reboot", "Cancel"]

    def on_select(self, app) -> None:
        options = self._options(app.state or {})
        self.selected = min(self.selected, len(options) - 1)
        if not self.confirming:
            self.confirming = True
            return
        choice = options[self.selected]
        if choice == "USB Disk":
            app.command("usb-storage-start")
        elif choice == "USB Stop":
            app.command("usb-storage-stop")
        elif choice == "Shutdown":
            app.command("shutdown")
        elif choice == "Reboot":
            app.command("reboot")
        self.confirming = False
        self.selected = 0

    def on_up(self, app) -> bool:
        if not self.confirming:
            return False
        options = self._options(app.state or {})
        self.selected = (self.selected - 1) % len(options)
        return True

    def on_down(self, app) -> bool:
        if not self.confirming:
            return False
        options = self._options(app.state or {})
        self.selected = (self.selected + 1) % len(options)
        return True

    def render(self, draw, width: int, height: int, context: dict) -> None:
        state = context.get("state") or {}
        options = self._options(state)
        self.selected = min(self.selected, len(options) - 1)
        font = _font(context, "font_medium")
        draw.text((0, HEADER_Y), "SYSTEM", font=font, fill=255)
        if not self.confirming:
            if state.get("mode") == "usb_transfer":
                draw.text((0, CONTENT_Y), "USB disk active", font=font, fill=255)
                draw.text((0, CONTENT_Y + LINE_HEIGHT), "Eject then stop", font=font, fill=255)
            else:
                draw.text((0, CONTENT_Y), "USB disk / power", font=font, fill=255)
                draw.text((0, CONTENT_Y + LINE_HEIGHT), "Press to choose", font=font, fill=255)
            return
        start = max(0, min(self.selected - 1, max(0, len(options) - 3)))
        for row, option_index in enumerate(range(start, min(start + 3, len(options)))):
            prefix = "> " if option_index == self.selected else "  "
            draw.text((0, CONTENT_Y + row * LINE_HEIGHT), prefix + options[option_index], font=font, fill=255)


class GameScreen(Screen):
    """A one-button Flappy Cat clone. It autostarts and auto-restarts after a
    crash; select flaps, up/down navigate away."""

    title = "HAVE FUN"

    # Play field: the header row is reserved for the title and high score.
    TOP = 13
    BIRD_X = 30
    BIRD_R = 3
    GRAVITY = 175.0
    FLAP_V = -54.0
    PIPE_W = 8
    PIPE_GAP = 24
    PIPE_SPEED = 34.0
    PIPE_SPACING = 60
    STEP = 1.0 / 60.0
    RESTART_DELAY = 1.2  # seconds the crash is shown before auto-restart

    def __init__(self) -> None:
        self.mode = "playing"  # playing | dead
        self.score = 0
        self.highscore = self._load_highscore()
        self.bird_y = 38.0
        self.bird_vy = 0.0
        self.pipes: list[dict[str, float | bool]] = []
        self._last_t: float | None = None
        self._accum = 0.0
        self._dead_at = 0.0
        self._start(64)

    # --- persistence -----------------------------------------------------
    def _highscore_path(self) -> Path | None:
        override = os.environ.get("FIREHAT_FLAPPY_HIGHSCORE_FILE")
        return Path(override) if override else None

    def _load_highscore(self) -> int:
        path = self._highscore_path()
        if path is None:
            return 0
        try:
            return int(path.read_text().strip() or "0")
        except (OSError, ValueError):
            return 0

    def _save_highscore(self) -> None:
        path = self._highscore_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(self.highscore))
        except OSError:
            pass

    # --- input -----------------------------------------------------------
    def _flap(self) -> None:
        self.bird_vy = self.FLAP_V

    def _start(self, height: int) -> None:
        self.mode = "playing"
        self.score = 0
        self.bird_y = (self.TOP + height) / 2.0
        self.bird_vy = self.FLAP_V
        self.pipes = []
        self._accum = 0.0
        self._last_t = None
        self._spawn_pipe(128.0)

    def on_select(self, app) -> None:
        if self.mode == "playing":
            self._flap()

    def on_up(self, app) -> bool:
        return False

    def on_down(self, app) -> bool:
        return False

    # --- simulation ------------------------------------------------------
    def _spawn_pipe(self, x: float) -> None:
        half = self.PIPE_GAP // 2
        center = random.randint(self.TOP + half + 2, 63 - half - 2)
        self.pipes.append({"x": x, "center": float(center), "scored": False})

    def _step(self, dt: float, height: int) -> None:
        ground = height - 1
        self.bird_vy += self.GRAVITY * dt
        self.bird_y += self.bird_vy * dt

        # The ceiling clamps the bird; only the ground and pipes are fatal.
        if self.bird_y - self.BIRD_R < self.TOP:
            self.bird_y = self.TOP + self.BIRD_R
            self.bird_vy = 0.0
        if self.bird_y + self.BIRD_R >= ground:
            self.bird_y = ground - self.BIRD_R
            self._game_over()
            return

        for pipe in self.pipes:
            pipe["x"] = float(pipe["x"]) - self.PIPE_SPEED * dt
            if not pipe["scored"] and float(pipe["x"]) + self.PIPE_W < self.BIRD_X:
                pipe["scored"] = True
                self.score += 1

        self.pipes = [p for p in self.pipes if float(p["x"]) + self.PIPE_W > 0]
        if not self.pipes or float(self.pipes[-1]["x"]) <= 128 - self.PIPE_SPACING:
            self._spawn_pipe(128.0)

        half = self.PIPE_GAP / 2.0
        for pipe in self.pipes:
            px = float(pipe["x"])
            if self.BIRD_X + self.BIRD_R > px and self.BIRD_X - self.BIRD_R < px + self.PIPE_W:
                gap_top = float(pipe["center"]) - half
                gap_bottom = float(pipe["center"]) + half
                if self.bird_y - self.BIRD_R < gap_top or self.bird_y + self.BIRD_R > gap_bottom:
                    self._game_over()
                    return

    def _game_over(self) -> None:
        self.mode = "dead"
        self._dead_at = time.monotonic()
        if self.score > self.highscore:
            self.highscore = self.score
            self._save_highscore()

    def _advance(self, height: int) -> None:
        now = time.monotonic()
        # Hold the crash on screen briefly, then auto-restart.
        if self.mode == "dead":
            if now - self._dead_at >= self.RESTART_DELAY:
                self._start(height)
            else:
                self._last_t = now
                return
        dt = 0.0 if self._last_t is None else now - self._last_t
        self._last_t = now
        if self.mode != "playing":
            return
        self._accum = min(0.25, self._accum + dt)
        while self._accum >= self.STEP:
            self._step(self.STEP, height)
            self._accum -= self.STEP
            if self.mode != "playing":
                break

    # --- rendering -------------------------------------------------------
    def _draw_cat(self, draw, y: float) -> None:
        x = self.BIRD_X
        cy = int(y)
        # Pointed ears at the top corners of the head.
        draw.polygon([(x - 3, cy - 2), (x - 1, cy - 2), (x - 3, cy - 5)], fill=255)
        draw.polygon([(x + 1, cy - 2), (x + 3, cy - 2), (x + 3, cy - 5)], fill=255)
        # Head/body blob and a tail curling off the back.
        draw.ellipse((x - 3, cy - 2, x + 3, cy + 3), fill=255)
        draw.line((x - 3, cy + 2, x - 6, cy), fill=255)
        draw.line((x - 6, cy, x - 6, cy - 2), fill=255)
        draw.point((x + 1, cy), fill=0)  # eye, facing the direction of travel

    def _draw_pipes(self, draw, height: int) -> None:
        half = self.PIPE_GAP // 2
        for pipe in self.pipes:
            x = int(float(pipe["x"]))
            center = int(float(pipe["center"]))
            draw.rectangle((x, self.TOP, x + self.PIPE_W - 1, center - half), fill=255)
            draw.rectangle((x, center + half, x + self.PIPE_W - 1, height - 1), fill=255)

    def render(self, draw, width: int, height: int, context: dict) -> None:
        font = _font(context, "font_medium")
        self._advance(height)

        self._draw_pipes(draw, height)
        self._draw_cat(draw, self.bird_y)

        # Header: title left, high score right, on a cleared strip.
        draw.rectangle((0, 0, width - 1, self.TOP - 2), fill=0)
        draw.text((0, HEADER_Y), self.title, font=font, fill=255)
        _right(draw, width, HEADER_Y, f"HI:{self.highscore}", font)
        _center(draw, width, HEADER_Y, str(self.score), font)


class LedTestScreen(Screen):
    """Prototyping screen: auto-cycles the LEDs through a broad palette of colors
    at a fixed opacity, shows the current RGBA on the OLED, and appends that value
    to a file when Select is pressed."""

    title = "LED TEST"

    # Advance to the next color this often.
    CYCLE_SECONDS = 1.5

    # Fixed opacity/brightness applied to every color.
    ALPHA = 64

    # Every combination of these per-channel levels (skipping all-off) — a much
    # wider palette than pure primaries: oranges, teals, pastels, greys, etc.
    LEVELS: list[int] = [0, 128, 255]

    def __init__(self) -> None:
        import colorsys

        colors = [
            (r, g, b)
            for r in self.LEVELS
            for g in self.LEVELS
            for b in self.LEVELS
            if (r, g, b) != (0, 0, 0)
        ]
        # Sort by hue (then brightest first) so the cycle reads as a rainbow.
        colors.sort(key=lambda c: (colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)[0], -sum(c)))
        self.combos = colors
        self.index = 0
        self._last_advance = time.monotonic()
        self._saved_flash_until = 0.0

    def _current(self) -> tuple[int, int, int]:
        return self.combos[self.index % len(self.combos)]

    def _advance_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_advance >= self.CYCLE_SECONDS:
            self.index = (self.index + 1) % len(self.combos)
            self._last_advance = now

    def led_override(self, app) -> "Rgb | None":
        self._advance_if_due()
        r, g, b = self._current()
        return Rgb(r, g, b).scaled(self.ALPHA / 255.0)

    # --- persistence -----------------------------------------------------
    def _save_path(self) -> Path:
        return Path(os.environ.get("FIREHAT_LED_TEST_FILE", "/home/firehat/led-test.txt"))

    def on_select(self, app) -> None:
        r, g, b = self._current()
        path = self._save_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as handle:
                handle.write(f"rgba({r}, {g}, {b}, {self.ALPHA})\n")
        except OSError:
            pass
        self._saved_flash_until = time.monotonic() + 1.0

    def render(self, draw, width: int, height: int, context: dict) -> None:
        self._advance_if_due()
        r, g, b = self._current()
        hex_code = f"#{r:02X}{g:02X}{b:02X}"
        font = _font(context, "font_medium")

        draw.text((0, HEADER_Y), self.title, font=font, fill=255)
        _right(draw, width, HEADER_Y, f"{self.index + 1:02d}/{len(self.combos):02d}", font)
        draw.text((0, 18), f"R{r:3d}  G{g:3d}", font=font, fill=255)
        draw.text((0, 33), f"B{b:3d}  A{self.ALPHA:3d}", font=font, fill=255)

        if time.monotonic() < self._saved_flash_until:
            _center(draw, width, 49, "SAVED", font)
        else:
            draw.text((0, 49), hex_code, font=font, fill=255)
            _right(draw, width, 49, "SEL=save", font)
