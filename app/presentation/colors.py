"""Presentation helpers for inventory row and warning status colors."""

from datetime import datetime

from app.config import utc_now


def get_row_color(last_checked: datetime | None) -> str:
    """Determine row color based on days since an item was last checked (UTC)."""
    if not last_checked:
        return "var(--inv-grey)"

    days_difference = (utc_now() - last_checked).days
    if days_difference < 1:
        return "var(--inv-green)"
    if days_difference < 4:
        return "var(--inv-orange)"
    if days_difference <= 8:
        return "var(--inv-darkorange)"
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
