from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any, Callable

SETTINGS_FILE_DEFAULT = "/etc/equip1/equip-1.ini"
LEGACY_LIGHTS_CONFIG_DEFAULT = "/etc/equip1/lights.json"
LIGHTS_BRIGHTNESS_DEFAULT = 0.25


class Equip1Settings:
    """Small INI-backed settings store for user-facing device preferences.

    The file is intentionally shared across settings areas so future user
    preferences can add sections instead of growing one-off JSON files.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path or os.environ.get("EQUIP1_SETTINGS_FILE", SETTINGS_FILE_DEFAULT)).expanduser()

    def get(self, section: str, option: str, default: str | None = None, *, env: str | None = None) -> str | None:
        if env and env in os.environ:
            return os.environ[env]
        parser = self._read()
        if not parser.has_section(section):
            return default
        return parser.get(section, option, fallback=default)

    def get_bool(self, section: str, option: str, default: bool = False, *, env: str | None = None) -> bool:
        if env and env in os.environ:
            return _parse_bool(os.environ[env], default)
        parser = self._read()
        if not parser.has_section(section):
            return default
        try:
            return parser.getboolean(section, option, fallback=default)
        except ValueError:
            return default

    def get_int(self, section: str, option: str, default: int, *, env: str | None = None) -> int:
        value = self.get(section, option, None, env=env)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, section: str, option: str, default: float, *, env: str | None = None) -> float:
        value = self.get(section, option, None, env=env)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def load_lights(
        self,
        *,
        count: int,
        fallback_colors: list[list[int]],
        coerce_colors: Callable[[Any, int], list[list[int]] | None],
    ) -> tuple[list[list[int]], bool, float] | None:
        parser = self._read()
        if not parser.has_section("lights"):
            return None

        colors = None
        raw_colors = parser.get("lights", "default_colors", fallback=None)
        if raw_colors:
            colors = coerce_colors(_parse_color_list(raw_colors), count)

        try:
            enabled = parser.getboolean("lights", "enabled", fallback=True)
        except ValueError:
            enabled = True
        brightness = self.get_float("lights", "brightness", LIGHTS_BRIGHTNESS_DEFAULT)
        return (colors if colors is not None else fallback_colors), enabled, _clamp_float(brightness, 0.0, 1.0)

    def save_lights(self, *, colors: list[list[int]], enabled: bool, brightness: float) -> None:
        parser = self._read()
        if not parser.has_section("lights"):
            parser.add_section("lights")
        parser.set("lights", "enabled", _format_bool(enabled))
        parser.set("lights", "brightness", _format_float(_clamp_float(brightness, 0.0, 1.0)))
        parser.set("lights", "default_colors", _format_colors(colors))
        self._write(parser)

    def _read(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        try:
            parser.read(self.path, encoding="utf-8")
        except configparser.Error:
            # Treat malformed settings as absent rather than taking down the
            # daemon; the next successful save will rewrite the file.
            return configparser.ConfigParser()
        return parser

    def _write(self, parser: configparser.ConfigParser) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _format_float(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _format_colors(colors: list[list[int]]) -> str:
    return ";".join(",".join(str(int(channel)) for channel in color[:3]) for color in colors)


def _parse_color_list(raw: str) -> list[list[str]]:
    return [
        [channel.strip() for channel in color.replace("/", ",").split(",")[:3]]
        for color in raw.replace("|", ";").split(";")
        if color.strip()
    ]
