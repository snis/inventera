"""Presentation helpers for inventory row and warning status colors."""

from datetime import datetime

from flask import has_app_context

from app.config import utc_now
from app.models.settings import Settings

DEFAULT_GREEN_DAYS = 1
DEFAULT_ORANGE_DAYS = 7


def get_row_color_thresholds() -> tuple[int, int]:
    """Return configured (green_days, orange_days) thresholds with safe defaults."""
    if not has_app_context():
        return DEFAULT_GREEN_DAYS, DEFAULT_ORANGE_DAYS
    try:
        green = int(
            Settings.get("row_color_green_days", str(DEFAULT_GREEN_DAYS)) or DEFAULT_GREEN_DAYS
        )
        orange = int(
            Settings.get("row_color_orange_days", str(DEFAULT_ORANGE_DAYS)) or DEFAULT_ORANGE_DAYS
        )
        if green >= 1 and orange >= green:
            return green, orange
    except (TypeError, ValueError):
        pass
    return DEFAULT_GREEN_DAYS, DEFAULT_ORANGE_DAYS


def get_row_color(last_checked: datetime | None) -> str:
    """Determine row color (green / orange / red) based on days since last check (UTC)."""
    if not last_checked:
        return "var(--inv-grey)"

    green_days, orange_days = get_row_color_thresholds()
    days_difference = (utc_now() - last_checked).days
    if days_difference < green_days:
        return "var(--inv-green)"
    if days_difference < orange_days:
        return "var(--inv-orange)"
    return "var(--inv-red)"


def get_warning_color(quantity: int | None, alert_quantity: int | None) -> str:
    """Determine warning color based on quantity relative to alert threshold."""
    if quantity is None or alert_quantity is None:
        return "var(--inv-grey)"

    diff = quantity - alert_quantity
    if diff == 0:
        return "var(--inv-orange)"
    if diff < 0:
        return "var(--inv-red)"
    return "var(--inv-green)"
