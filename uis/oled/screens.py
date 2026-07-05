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
