from __future__ import annotations

from typing import Any


HEADER_Y = 0


def draw_battery_indicator(draw, width: int, height: int, context: dict[str, Any]) -> None:
    """Draw a compact PiSugar battery indicator in the header area.

    The indicator is data-driven from daemon state. If the power monitor is not
    available, nothing is drawn so non-PiSugar builds keep their existing UI.
    """

    power = (context.get("state") or {}).get("power") or {}
    if not power.get("available"):
        return

    try:
        battery_percent = max(0, min(100, int(round(float(power.get("battery_percent"))))))
    except (TypeError, ValueError):
        return

    fonts = context.get("fonts")
    font = getattr(fonts, "font_medium", None) if fonts is not None else None
    text = f"{battery_percent}%"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]

    icon_width = 5
    icon_height = 10
    gap = 3
    total_width = icon_width + gap + text_width
    icon_x = max(0, (width - total_width) // 2)
    icon_y = HEADER_Y + 2
    text_x = icon_x + icon_width + gap

    # Battery body and terminal. Coordinates are kept fully in-bounds for PIL's
    # 1-bit renderer and the hardware OLED backend.
    body_top = icon_y + 1
    body_bottom = min(height - 1, icon_y + icon_height - 1)
    body_right = icon_x + icon_width - 1
    draw.rectangle((icon_x, body_top, body_right, body_bottom), outline=255, fill=0)
    if icon_width >= 3 and icon_y >= 0:
        draw.line((icon_x + 1, icon_y, body_right - 1, icon_y), fill=255)

    # Fill from the bottom up. The text gives the exact percentage; the icon fill
    # is a quick peripheral cue, especially useful at low battery.
    inner_left = icon_x + 1
    inner_right = body_right - 1
    inner_top = body_top + 1
    inner_bottom = body_bottom - 1
    inner_height = max(0, inner_bottom - inner_top + 1)
    fill_height = round(inner_height * battery_percent / 100)
    if fill_height > 0 and inner_left <= inner_right:
        fill_top = inner_bottom - fill_height + 1
        draw.rectangle((inner_left, fill_top, inner_right, inner_bottom), fill=255)

    if power.get("charging") or power.get("external_power"):
        # Tiny plug/charge mark just to the left of the icon. It is deliberately
        # understated so it does not compete with the existing header labels.
        plug_x = max(0, icon_x - 3)
        draw.point((plug_x, icon_y + 3), fill=255)
        draw.point((plug_x + 1, icon_y + 4), fill=255)
        draw.point((plug_x, icon_y + 5), fill=255)

    draw.text((text_x, HEADER_Y), text, font=font, fill=255)
