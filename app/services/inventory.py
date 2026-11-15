"""Inventory query services."""

from app.models.item import Item
from app.utils.i18n import t


def get_items_by_location() -> dict[str, list[Item]]:
    """Get visible items grouped by physical location, sorted alphabetically."""
    other_label = t("common.other")
    items = Item.query.filter(Item.is_visible.is_(True)).order_by(Item.name).all()
    grouped: dict[str, list[Item]] = {}

    for item in items:
        loc = (item.location or "").strip() or other_label
        grouped.setdefault(loc, []).append(item)

    ordered: dict[str, list[Item]] = {
        loc: grouped[loc] for loc in sorted(k for k in grouped if k != other_label)
    }
    if other_label in grouped:
        ordered[other_label] = grouped[other_label]
    return ordered


def get_low_stock_by_store() -> dict[str, list[Item]]:
    """Get visible items at or below alert threshold, grouped by store."""
    other_label = t("common.other")
    items = (
        Item.query.filter(Item.is_visible.is_(True), Item.quantity <= Item.alert_quantity)
        .order_by(Item.name)
        .all()
    )
    grouped: dict[str, list[Item]] = {}

    for item in items:
        store = (item.store or "").strip() or other_label
        grouped.setdefault(store, []).append(item)

    ordered: dict[str, list[Item]] = {
        store: grouped[store] for store in sorted(k for k in grouped if k != other_label)
    }
    if other_label in grouped:
        ordered[other_label] = grouped[other_label]
    return ordered
