from __future__ import annotations

import array
import fcntl
import os
import time
from dataclasses import dataclass


SPI_IOC_WR_MODE = 0x40016B01
SPI_IOC_WR_BITS_PER_WORD = 0x40016B03
SPI_IOC_WR_MAX_SPEED_HZ = 0x40046B04


@dataclass(frozen=True)
class Rgb:
    r: int
    g: int
    b: int
    w: int = 0

    def scaled(self, factor: float) -> "Rgb":
        return Rgb(
            r=max(0, min(255, round(self.r * factor))),
            g=max(0, min(255, round(self.g * factor))),
            b=max(0, min(255, round(self.b * factor))),
            w=max(0, min(255, round(self.w * factor))),
        )


# Status LED colors, used as the exact emitted RGB value (no extra scaling):
# dim green when a camera is ready, dim red while recording, dim blue when no
# camera is attached, dim magenta on the game screen.
STATUS_READY = Rgb(0, 16, 0)
STATUS_RECORDING = Rgb(16, 0, 0)
STATUS_NO_CAMERA = Rgb(0, 0, 16)
STATUS_GAME = Rgb(16, 0, 16)


class NullLeds:
    def boot_marquee(self, elapsed: float) -> None:
        pass

    def set_status(self, color: "Rgb | None") -> None:
        pass

    def set_all(self, color: "Rgb") -> None:
        pass

    def clear(self) -> None:
        pass

    def close(self) -> None:
        pass


class Ws2812SpiLeds:
    """SPI encoder for SK6812/WS2812-style addressable LEDs.

    The Firehat PCB uses SK6812-EC20 LEDs on the Rock 2F 40-pin header pin 19
    (SPI0_MOSI). SK6812-EC20 is GRB order and wants 800 kHz one-wire NRZ.

    Default encoding is conservative for SK6812:
      SPI 3.2 MHz, 4 SPI bits per LED bit
      LED 0 -> 1000  (T0H ≈ 0.31 µs, safely below SK6812 max 0.4 µs)
      LED 1 -> 1110  (T1H ≈ 0.94 µs, within SK6812 max 1.0 µs)
    This is more reliable than the older 2.4 MHz 3-bit encoding whose zero high
    pulse was marginal for SK6812 and could leave pixels stuck on.
    """

    def __init__(
        self,
        device: str = "/dev/spidev0.0",
        count: int = 3,
        speed_hz: int = 3_200_000,
        color_order: str = "GRB",
        color: Rgb = Rgb(255, 135, 35),
        trail_factor: float = 0.20,
        step_seconds: float = 0.28,
        brightness: float = 0.25,
        symbol_bits: int = 4,
        zero_symbol: int = 0b1000,
        one_symbol: int = 0b1110,
    ) -> None:
        self.device = device
        self.count = count
        self.speed_hz = speed_hz
        self.color_order = color_order.upper()
        self.color = color
        self.trail_factor = trail_factor
        self.step_seconds = step_seconds
        self.brightness = brightness
        self.symbol_bits = symbol_bits
        self.zero_symbol = zero_symbol
        self.one_symbol = one_symbol
        self._fd = os.open(device, os.O_WRONLY)
        self._last_frame: tuple[Rgb, ...] | None = None
        self._configure_spi()
        self.clear()

    def _configure_spi(self) -> None:
        mode = array.array("B", [0])
        bits = array.array("B", [8])
        speed = array.array("I", [self.speed_hz])
        fcntl.ioctl(self._fd, SPI_IOC_WR_MODE, mode, True)
        fcntl.ioctl(self._fd, SPI_IOC_WR_BITS_PER_WORD, bits, True)
        fcntl.ioctl(self._fd, SPI_IOC_WR_MAX_SPEED_HZ, speed, True)

    def boot_marquee(self, elapsed: float) -> None:
        if self.count <= 0:
            return

        # Smooth ping-pong position: left -> right -> left.
        if self.count == 1:
            position = 0.0
            span = 1.0
        else:
            span = self.count - 1
            phase = (elapsed / self.step_seconds) % (span * 2)
            position = phase if phase <= span else (span * 2) - phase

        # Rainbow rotation: base hue sweeps slowly, each LED is 120° apart.
        base_hue = (elapsed * 60.0) % 360.0

        frame: list[Rgb] = []
        for idx in range(self.count):
            distance = abs(idx - position)
            intensity = max(0.0, 1.0 - (distance / 1.18))
            intensity = intensity * intensity
            if intensity < 0.02:
                intensity = 0.0
            intensity = max(intensity, self.trail_factor if distance < 1.05 else 0.0)
            intensity *= self.brightness

            hue = (base_hue + idx * 120.0) % 360.0
            frame.append(self._hsv_to_rgb(hue, 1.0, intensity))
        self.write(frame)

    def set_status(self, color: "Rgb | None") -> None:
        """Light all LEDs with ``color`` as the exact emitted value. Passing
        ``None`` turns them off."""
        fill = Rgb(0, 0, 0) if color is None else color
        self.write([fill] * self.count)

    def set_all(self, color: "Rgb") -> None:
        """Drive every LED with ``color`` exactly as given, bypassing the fixed
        status brightness. Used by the LED test screen so its alpha/opacity maps
        straight to the emitted value."""
        self.write([color] * self.count)

    def clear(self) -> None:
        off = [Rgb(0, 0, 0, 0)] * self.count
        # Send several separated off frames. The sleeps are intentional: they
        # provide full SK6812 reset/latch intervals between attempts, which is
        # much more reliable than back-to-back writes when recovering from a
        # marginal previous frame.
        for _ in range(6):
            self.write(off, force=True)
            time.sleep(0.003)
        self._last_frame = None

    def write(self, colors: list[Rgb], force: bool = False) -> None:
        frame = tuple(colors[: self.count])
        if not force and frame == self._last_frame:
            return
        self._last_frame = frame
        payload = bytearray()
        for color in frame:
            payload.extend(self._encode_color(color))
        # Keep MOSI low long enough for SK6812 reset/latch (>80 µs). At 3.2 MHz,
        # 512 zero bytes is >1.2 ms of low/reset time.
        payload.extend(b"\x00" * 512)
        os.write(self._fd, payload)

    @staticmethod
    def _hsv_to_rgb(h: float, s: float, v: float) -> Rgb:
        """HSV to Rgb. h in [0,360), s/v in [0,1]."""
        h = h % 360.0
        c = v * s
        x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
        m = v - c
        if h < 60.0:
            r, g, b = c, x, 0.0
        elif h < 120.0:
            r, g, b = x, c, 0.0
        elif h < 180.0:
            r, g, b = 0.0, c, x
        elif h < 240.0:
            r, g, b = 0.0, x, c
        elif h < 300.0:
            r, g, b = x, 0.0, c
        else:
            r, g, b = c, 0.0, x
        return Rgb(
            r=max(0, min(255, round((r + m) * 255.0))),
            g=max(0, min(255, round((g + m) * 255.0))),
            b=max(0, min(255, round((b + m) * 255.0))),
        )

    def _encode_color(self, color: Rgb) -> bytes:
        channels = {
            "R": color.r,
            "G": color.g,
            "B": color.b,
            "W": color.w,
        }
        data = bytearray()
        for channel in self.color_order:
            self._encode_byte(channels.get(channel, 0), data)
        return bytes(data)

    def _encode_byte(self, value: int, out: bytearray) -> None:
        bits = 0
        bit_count = 0
        for shift in range(7, -1, -1):
            symbol = self.one_symbol if (value & (1 << shift)) else self.zero_symbol
            bits = (bits << self.symbol_bits) | symbol
            bit_count += self.symbol_bits
            while bit_count >= 8:
                bit_count -= 8
                out.append((bits >> bit_count) & 0xFF)
        if bit_count:
            out.append((bits << (8 - bit_count)) & 0xFF)

    def close(self) -> None:
        try:
            self.clear()
        finally:
            os.close(self._fd)


def _env_enabled(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def _env_rgb(name: str, default: Rgb) -> Rgb:
    value = os.environ.get(name)
    if not value:
        return default
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) not in {3, 4}:
        raise ValueError(f"{name} must be R,G,B or R,G,B,W")
    return Rgb(*[max(0, min(255, part)) for part in parts])


def _env_int_auto(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    return int(value, 0)


def make_boot_leds():
    if not _env_enabled("FIREHAT_RGB_LED_ENABLED", default=True):
        return NullLeds()
    backend = os.environ.get("FIREHAT_RGB_LED_BACKEND", "spi").lower()
    if backend != "spi":
        print(f"RGB LED backend {backend!r} is not supported; disabling LEDs", flush=True)
        return NullLeds()

    device = os.environ.get("FIREHAT_RGB_LED_SPI_DEVICE", "/dev/spidev0.0")
    try:
        return Ws2812SpiLeds(
            device=device,
            count=int(os.environ.get("FIREHAT_RGB_LED_COUNT", "3")),
            speed_hz=int(os.environ.get("FIREHAT_RGB_LED_SPI_HZ", "3200000")),
            color_order=os.environ.get("FIREHAT_RGB_LED_ORDER", "GRB"),
            color=_env_rgb("FIREHAT_RGB_LED_COLOR", Rgb(255, 135, 35)),
            brightness=float(os.environ.get("FIREHAT_RGB_LED_BRIGHTNESS", "0.25")),
            trail_factor=float(os.environ.get("FIREHAT_RGB_LED_TRAIL_FACTOR", "0.20")),
            step_seconds=float(os.environ.get("FIREHAT_RGB_LED_STEP_SECONDS", "0.28")),
            symbol_bits=int(os.environ.get("FIREHAT_RGB_LED_SYMBOL_BITS", "4")),
            zero_symbol=_env_int_auto("FIREHAT_RGB_LED_ZERO_SYMBOL", 0b1000),
            one_symbol=_env_int_auto("FIREHAT_RGB_LED_ONE_SYMBOL", 0b1110),
        )
    except Exception as exc:
        print(f"RGB LEDs disabled: {exc}", flush=True)
        return NullLeds()
