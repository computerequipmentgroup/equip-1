from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .config import BoardConfig

DrawFunc = Callable[[object, int, int, dict], None]


class ScaledBitmapFont:
    """A native bitmap font drawn at an integer scale with nearest-neighbor pixels."""

    def __init__(self, base_font, scale: int = 1):
        self.base_font = base_font
        self.scale = scale
        self.path = getattr(base_font, "path", None)


class OledDraw:
    """ImageDraw proxy that knows how to render ScaledBitmapFont instances."""

    def __init__(self, image, draw):
        self.image = image
        self.draw = draw

    def __getattr__(self, name: str):
        return getattr(self.draw, name)

    def textbbox(self, xy, text, font=None, *args, **kwargs):
        if isinstance(font, ScaledBitmapFont):
            x, y = xy
            left, top, right, bottom = self.draw.textbbox((0, 0), text, font=font.base_font, *args, **kwargs)
            return (
                x + left * font.scale,
                y + top * font.scale,
                x + right * font.scale,
                y + bottom * font.scale,
            )
        return self.draw.textbbox(xy, text, font=font, *args, **kwargs)

    def text(self, xy, text, font=None, fill=None, *args, **kwargs):
        if not isinstance(font, ScaledBitmapFont):
            return self.draw.text(xy, text, font=font, fill=fill, *args, **kwargs)

        from PIL import Image, ImageDraw

        scale = font.scale
        left, top, right, bottom = self.draw.textbbox((0, 0), text, font=font.base_font, *args, **kwargs)
        width = max(1, right - left)
        height = max(1, bottom - top)
        mask = Image.new("1", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text((-left, -top), text, font=font.base_font, fill=1, *args, **kwargs)
        if scale != 1:
            mask = mask.resize((width * scale, height * scale), Image.Resampling.NEAREST)
        x, y = xy
        color = 255 if fill is None else fill
        self.image.paste(color, (x + left * scale, y + top * scale), mask)


class OledFontSet:
    """Fonts used by both the hardware display and software/browser previews."""

    def __init__(self):
        from PIL import ImageFont

        self.font_small = self._font(ImageFont, "fonts/Bm437_DOS-V_re_JPN12.otb", 12)
        self.font_medium = self.font_small
        self.font_big = ScaledBitmapFont(self._font(ImageFont, "fonts/Bm437_Paradise132_7x16.otb", 16), scale=2)
        self.font_boot = self._font(ImageFont, "fonts/w.ttf", 9)

    def _font(self, image_font, relative_path: str, size: int):
        package_path = Path(__file__).resolve()
        candidates = [Path(relative_path)]
        candidates.extend(parent / relative_path for parent in package_path.parents)
        font_dir = os.environ.get("FIREHAT_FONT_DIR")
        if font_dir:
            candidates.append(Path(font_dir) / Path(relative_path).name)
        for path in candidates:
            if path and path.exists():
                try:
                    return image_font.truetype(str(path), size)
                except OSError:
                    pass
        return image_font.load_default()


def render_oled_image(
    draw_func: DrawFunc,
    context: dict,
    width: int = 128,
    height: int = 64,
    fonts: OledFontSet | None = None,
):
    """Render an OLED screen into a 1-bit PIL image without OLED hardware."""
    from PIL import Image, ImageDraw

    img = Image.new("1", (width, height))
    draw = OledDraw(img, ImageDraw.Draw(img))
    context = {**context, "fonts": fonts or OledFontSet()}
    draw_func(draw, width, height, context)
    return img


class OledDisplay:
    def __init__(self, board: BoardConfig):
        from luma.core.interface.serial import i2c
        from luma.oled.device import sh1106

        serial = i2c(port=board.i2c_port, address=board.oled_address)
        self.device = sh1106(serial)
        self.width = self.device.width
        self.height = self.device.height
        self.fonts = OledFontSet()
        self.font_small = self.fonts.font_small
        self.font_medium = self.fonts.font_medium
        self.font_big = self.fonts.font_big

    def clear(self) -> None:
        from PIL import Image

        self.device.display(Image.new("1", self.device.size))

    def render(self, draw_func: DrawFunc, context: dict) -> None:
        img = render_oled_image(draw_func, context, self.width, self.height, self.fonts)
        self.device.display(img)


class ConsoleDisplay:
    """Development fallback for running the OLED client without hardware."""

    width = 128
    height = 64
    font_small = None
    font_medium = None
    font_big = None

    def clear(self) -> None:
        pass

    def render(self, draw_func: DrawFunc, context: dict) -> None:
        state = context.get("state") or {}
        print(f"OLED {state.get('mode', 'offline')} {state.get('recording', {}).get('elapsed_seconds', '')}")


def make_display(board: BoardConfig):
    if os.environ.get("FIREHAT_OLED_MOCK") == "1":
        return ConsoleDisplay()

    settle_delay = float(os.environ.get("FIREHAT_OLED_SETTLE_DELAY", "0"))
    attempts = int(os.environ.get("FIREHAT_OLED_INIT_ATTEMPTS", "120"))
    delay = float(os.environ.get("FIREHAT_OLED_INIT_DELAY", "1"))
    if settle_delay > 0:
        print(f"Waiting {settle_delay:g}s before OLED init", flush=True)
        time.sleep(settle_delay)

    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            display = OledDisplay(board)
            if attempt > 1:
                print(f"OLED init succeeded on attempt {attempt}/{attempts}", flush=True)
            return display
        except OSError as exc:
            last_error = exc
            print(
                f"OLED init failed on i2c-{board.i2c_port} address 0x{board.oled_address:02x} "
                f"(attempt {attempt}/{attempts}): {exc}",
                flush=True,
            )
            if attempt < attempts:
                time.sleep(delay)

    assert last_error is not None
    raise last_error
