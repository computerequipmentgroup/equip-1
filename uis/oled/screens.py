from __future__ import annotations

import time
from typing import Any

from .formatting import bytes_gb, hhmmss, percent


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

    def can_navigate(self, state: dict[str, Any]) -> bool:
        return False

    def render(self, draw, width: int, height: int, context: dict) -> None:
        elapsed = float(context.get("boot_elapsed", time.monotonic() % 2.5))
        duration = max(0.1, float(context.get("boot_duration_seconds", 2.5)))

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

        fade_start = duration * 0.24
        if elapsed <= fade_start:
            return

        fade = max(0.0, min(1.0, (elapsed - fade_start) / (duration - fade_start)))
        fade_eased = fade * fade * (3.0 - 2.0 * fade)
        threshold = int(fade_eased * 256)

        from PIL import Image, ImageDraw

        from .display import OledDraw

        target = Image.new("1", (width, height))
        target_state = context.get("state") or {}
        if target_state.get("mode") == "boot":
            target_state = {"mode": "idle", "recording": {"active": False, "elapsed_seconds": 0}, "storage": {"recording_minutes_available": 0}}
        RecordingScreen().render(OledDraw(target, ImageDraw.Draw(target)), width, height, {**context, "state": target_state})
        target_pixels = [(px, py) for py in range(height) for px in range(width) if target.getpixel((px, py))]

        image = getattr(draw, "image", None)
        text_pixels: list[tuple[int, int, int]] = []
        for x, y, bbox in text_positions:
            for py in range(max(0, y + bbox[1]), min(height, y + bbox[3])):
                for px in range(max(0, x + bbox[0]), min(width, x + bbox[2])):
                    if image is not None and not image.getpixel((px, py)):
                        continue
                    seed = (px * 1103515245 + py * 12345 + 97) & 0x7FFFFFFF
                    if seed % 256 < threshold:
                        text_pixels.append((px, py, seed))

        drift = min(1.0, fade_eased * 1.08)
        morph_visibility = int((1.0 - max(0.0, min(1.0, (fade - 0.78) / 0.22))) * 256)
        for px, py, seed in text_pixels:
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


def _wifi_qr_image(ssid: str, password: str, max_size: int):
    from PIL import Image
    import qrcode

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(_wifi_qr_payload(ssid, password))
    qr.make(fit=True)
    # OLED pixels are visible when they are white/lit.  Render the QR modules
    # as lit pixels on the black OLED background; normal black-on-white QR
    # polarity looks like sparse dots/holes on this display.
    image = qr.make_image(fill_color="white", back_color="black").convert("1")
    scale = max(1, max_size // max(image.size))
    scaled_size = (image.width * scale, image.height * scale)
    if scaled_size != image.size and max(scaled_size) <= max_size:
        image = image.resize(scaled_size, Image.Resampling.NEAREST)
    return image


class NetworkScreen(Screen):
    title = "NETWORK"

    def __init__(self) -> None:
        self.show_qr = False
        self._qr_key: tuple[str, str] | None = None
        self._qr_image = None

    def on_select(self, app) -> None:
        network = (app.state or {}).get("network") or {}
        if network.get("ssid") and network.get("password"):
            self.show_qr = not self.show_qr

    def on_up(self, app) -> bool:
        if self.show_qr:
            self.show_qr = False
            return True
        return False

    def on_down(self, app) -> bool:
        if self.show_qr:
            self.show_qr = False
            return True
        return False

    def _render_qr(self, draw, width: int, height: int, ssid: str, password: str, font) -> None:
        try:
            key = (ssid, password)
            if self._qr_key != key or self._qr_image is None:
                self._qr_image = _wifi_qr_image(ssid, password, min(width, height))
                self._qr_key = key
            x = (width - self._qr_image.width) // 2
            y = (height - self._qr_image.height) // 2
            draw.image.paste(self._qr_image, (x, y))
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
        if self.show_qr and ssid and password:
            self._render_qr(draw, width, height, str(ssid), str(password), font)
            return

        self.show_qr = False
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


class SystemScreen(Screen):
    title = "SYSTEM"

    def __init__(self) -> None:
        self.options = ["Shutdown", "Reboot", "Cancel"]
        self.selected = 0
        self.confirming = False

    def on_select(self, app) -> None:
        if not self.confirming:
            self.confirming = True
            return
        choice = self.options[self.selected]
        if choice == "Shutdown":
            app.command("shutdown")
        elif choice == "Reboot":
            app.command("reboot")
        self.confirming = False
        self.selected = 0

    def on_up(self, app) -> bool:
        if not self.confirming:
            return False
        self.selected = (self.selected - 1) % len(self.options)
        return True

    def on_down(self, app) -> bool:
        if not self.confirming:
            return False
        self.selected = (self.selected + 1) % len(self.options)
        return True

    def render(self, draw, width: int, height: int, context: dict) -> None:
        font = _font(context, "font_medium")
        draw.text((0, HEADER_Y), "SYSTEM", font=font, fill=255)
        if not self.confirming:
            draw.text((0, CONTENT_Y), "Press for power", font=font, fill=255)
            draw.text((0, CONTENT_Y + LINE_HEIGHT), "Shutdown/Reboot", font=font, fill=255)
            return
        for i, option in enumerate(self.options):
            prefix = "> " if i == self.selected else "  "
            draw.text((0, CONTENT_Y + i * LINE_HEIGHT), prefix + option, font=font, fill=255)
