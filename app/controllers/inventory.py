"""
Inventory blueprint for the inventory application.
Contains routes for inventory management operations.
"""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.config import utc_now
from app.extensions import db
from app.models.item import Item, Location, Store, Unit
from app.presentation.colors import get_row_color, get_warning_color
from app.services.inventory import get_low_stock_by_store
from app.services.options import get_managed_options
from app.services.shopping_sync import sync_low_inventory_to_ha
from app.utils.i18n import t
from app.utils.responses import create_response, is_ajax_request

inventory_bp = Blueprint("inventory", __name__)


MAX_SQLITE_INT = 2_147_483_647


class _ItemConflictError(Exception):
    """Raised on duplicate item name or optimistic-locking version mismatch."""


def _parse_non_negative_int(raw: str | None, field_label: str) -> int:
    """Parse a non-negative integer within SQLite 32-bit safe bounds or raise ValueError."""
    if raw is None or not raw.strip().isdigit():
        raise ValueError(f"Invalid non-negative integer for {field_label}")
    val = int(raw.strip())
    if val > MAX_SQLITE_INT:
        raise ValueError(f"Value out of range for {field_label}")
    return val


def _resolve_option(model, raw_id: str | None, *, required: bool = False):
    """Resolve an option row by ID string, raising ValueError if invalid or out of range."""
    clean = (raw_id or "").strip()
    if not clean:
        if required:
            raise ValueError(t("api.missing_fields"))
        return None
    opt_id = _parse_non_negative_int(clean, "option_id")
    obj = db.session.get(model, opt_id)
    if not obj:
        raise ValueError(f"Option not found: {opt_id}")
    return obj


def _check_version(item: Item, raw_version: str | None) -> None:
    """Verify optimistic-locking version when provided by the client."""
    if raw_version is None or not raw_version.strip():
        return
    expected_version = _parse_non_negative_int(raw_version, "version")
    current_version = item.version if item.version is not None else 1
    if expected_version != current_version:
        raise _ItemConflictError(t("api.item_conflict"))


def _ensure_unique_item_name(name: str, *, exclude_item_id: int | None = None) -> None:
    """Ensure item names are unique case-insensitively across Unicode characters."""
    query = Item.query.filter_by(name_key=name.casefold())
    if exclude_item_id is not None:
        query = query.filter(Item.id != exclude_item_id)
    if query.first() is not None:
        raise _ItemConflictError(t("api.duplicate_item", name=name))


def _apply_item_update(item: Item, item_id: int) -> None:
    """Validate and apply form updates to an existing Item."""
    _check_version(item, request.form.get(f"version_{item_id}"))

    name = (request.form.get(f"name_{item_id}") or "").strip()
    if not name:
        raise ValueError(t("api.missing_fields"))
    _ensure_unique_item_name(name, exclude_item_id=item_id)

    quantity = _parse_non_negative_int(request.form.get(f"quantity_{item_id}"), "quantity")
    alert_quantity = _parse_non_negative_int(
        request.form.get(f"alert_quantity_{item_id}"), "alert_quantity"
    )
    unit_obj = _resolve_option(Unit, request.form.get(f"unit_{item_id}"), required=False)
    loc_obj = _resolve_option(Location, request.form.get(f"location_{item_id}"))
    store_obj = _resolve_option(Store, request.form.get(f"store_{item_id}"))

    quantity_changed = item.quantity != quantity
    item.name = name
    item.quantity = quantity
    item.alert_quantity = alert_quantity
    item.unit_id = unit_obj.id if unit_obj else None
    item.unit = unit_obj.name if unit_obj else ""
    item.location_id = loc_obj.id if loc_obj else None
    item.location = loc_obj.name if loc_obj else ""
    item.store_id = store_obj.id if store_obj else None
    item.store = store_obj.name if store_obj else ""
    if quantity_changed or item.last_checked is None:
        item.last_checked = utc_now()
    item.version = (item.version or 1) + 1


def _create_item_from_form() -> Item:
    """Validate form inputs and build a new Item instance."""
    new_name = (request.form.get("new_name") or "").strip()
    if not new_name:
        raise ValueError(t("api.missing_fields"))
    _ensure_unique_item_name(new_name)

    unit_obj = _resolve_option(Unit, request.form.get("new_unit"), required=True)
    loc_obj = _resolve_option(Location, request.form.get("new_location"))
    store_obj = _resolve_option(Store, request.form.get("new_store"))

    raw_qty = request.form.get("new_quantity")
    raw_alert = request.form.get("new_alert_quantity")
    new_quantity = _parse_non_negative_int(raw_qty, "new_quantity") if raw_qty else 0
    new_alert_quantity = (
        _parse_non_negative_int(raw_alert, "new_alert_quantity") if raw_alert else 0
    )

    return Item(
        name=new_name,
        quantity=new_quantity,
        alert_quantity=new_alert_quantity,
        unit=unit_obj.name,
        unit_id=unit_obj.id,
        category="",
        location=loc_obj.name if loc_obj else "",
        location_id=loc_obj.id if loc_obj else None,
        store=store_obj.name if store_obj else "",
        store_id=store_obj.id if store_obj else None,
        last_checked=utc_now(),
    )


@inventory_bp.route("/shopping")
def shopping():
    """Render shopping list view grouped by store/supplier for all items needing restock."""
    try:
        low_stock = get_low_stock_by_store()
        return render_template("shopping.html", low_stock_by_store=low_stock)
    except Exception:
        current_app.logger.exception("Error rendering shopping list")
        return render_template("error.html", message=t("common.error_generic")), 500


@inventory_bp.route("/sync_ha", methods=["POST"])
def sync_ha():
    """Sync all items below safety threshold to Home Assistant Todo lists."""
    try:
        result = sync_low_inventory_to_ha()
        status_code = 502 if result.get("status") == "error" else 200
        return jsonify(result), status_code
    except Exception:
        current_app.logger.exception("Error syncing to Home Assistant")
        return jsonify({"status": "error", "message": t("common.error_generic")}), 500


@inventory_bp.route("/update_quantity", methods=["POST"])
def update_quantity():
    """Update the quantity of an inventory item."""
    try:
        item_id = _parse_non_negative_int(request.form.get("item_id"), "item_id")
        new_quantity = _parse_non_negative_int(request.form.get("new_quantity"), "new_quantity")
    except ValueError:
        return create_response(
            success=False,
            message=t("api.invalid_quantity"),
            redirect_url=url_for("main.index"),
            status_code=400,
        )

    try:
        item = db.session.get(Item, item_id)
        if not item:
            return create_response(
                success=False,
                message=t("api.item_not_found"),
                redirect_url=url_for("main.index"),
                status_code=404,
            )

        _check_version(item, request.form.get("version"))
        item.quantity = new_quantity
        item.last_checked = utc_now()
        item.version = (item.version or 1) + 1
        db.session.commit()

        if is_ajax_request():
            return jsonify(
                {
                    "status": "success",
                    "item_id": item_id,
                    "new_quantity": new_quantity,
                    "version": item.version,
                    "last_checked": item.last_checked.strftime("%d/%m"),
                    "row_color": get_row_color(item.last_checked),
                    "warning_color": get_warning_color(item.quantity, item.alert_quantity),
                    "button_class": "",
                }
            )
        return redirect(url_for("main.index"))
    except ValueError:
        db.session.rollback()
        return create_response(
            success=False,
            message=t("api.invalid_quantity"),
            redirect_url=url_for("main.index"),
            status_code=400,
        )
    except (_ItemConflictError, StaleDataError) as e:
        db.session.rollback()
        return create_response(
            success=False,
            message=t("api.item_conflict") if isinstance(e, StaleDataError) else str(e),
            redirect_url=url_for("main.index"),
            status_code=409,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error updating quantity")
        return create_response(
            success=False,
            message=t("common.error_generic"),
            redirect_url=url_for("main.index"),
            status_code=500,
        )


@inventory_bp.route("/inventory")
@inventory_bp.route("/inventory/<int:page>")
def inventory(page: int = 1):
    """Render the inventory management page with sorting and pagination."""
    try:
        items_per_page = 50

        sort_by = request.args.get("sort", "location")
        if sort_by not in ("name", "location", "store"):
            sort_by = "location"
        sort_dir = request.args.get("dir", "asc")
        if sort_dir not in ("asc", "desc"):
            sort_dir = "asc"

        sort_columns = {
            "name": db.func.lower(Item.name),
            "location": db.func.lower(db.func.coalesce(Item.location, "")),
            "store": db.func.lower(db.func.coalesce(Item.store, "")),
        }
        primary_col = sort_columns[sort_by]
        primary_order = primary_col.desc() if sort_dir == "desc" else primary_col.asc()

        query = Item.query.order_by(primary_order, db.func.lower(Item.name).asc())
        total_items = query.count()
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        items = query.limit(items_per_page).offset((page - 1) * items_per_page).all()
        start_page = max(1, page - 2)
        end_page = min(total_pages, page + 2)

        return render_template(
            "inventory.html",
            items=items,
            sort_by=sort_by,
            sort_dir=sort_dir,
            distinct_units=get_managed_options("unit"),
            distinct_locations=get_managed_options("location"),
            distinct_stores=get_managed_options("store"),
            get_row_color=get_row_color,
            get_warning_color=get_warning_color,
            pagination={
                "page": page,
                "total_pages": total_pages,
                "start_page": start_page,
                "end_page": end_page,
                "has_prev": page > 1,
                "has_next": page < total_pages,
                "total_items": total_items,
            },
        )
    except Exception:
        current_app.logger.exception("Error rendering inventory page")
        return render_template("error.html", message=t("common.error_generic")), 500


@inventory_bp.route("/update_items", methods=["POST"])
def update_items():
    """Update existing inventory items or add a new item."""
    try:
        updated_item: Item | None = None
        for key, value in request.form.items():
            if key.startswith("update_item"):
                item_id = _parse_non_negative_int(value, "item_id")
                item = db.session.get(Item, item_id)
                if not item:
                    return create_response(
                        success=False,
                        message=t("api.item_not_found"),
                        redirect_url=url_for("inventory.inventory"),
                        status_code=404,
                    )
                _apply_item_update(item, item_id)
                updated_item = item

        if "add_item" in request.form:
            db.session.add(_create_item_from_form())

        db.session.commit()

        if updated_item and is_ajax_request():
            return jsonify(
                {
                    "status": "success",
                    "item_id": updated_item.id,
                    "item": updated_item.to_dict(),
                    "row_color": get_row_color(updated_item.last_checked),
                    "warning_color": get_warning_color(
                        updated_item.quantity, updated_item.alert_quantity
                    ),
                }
            )

        if "add_item" in request.form and is_ajax_request():
            return jsonify({"status": "success", "message": t("api.item_added")})

        return redirect(url_for("inventory.inventory"))
    except ValueError as e:
        db.session.rollback()
        return create_response(
            success=False,
            message=str(e),
            redirect_url=url_for("inventory.inventory"),
            status_code=400,
        )
    except (_ItemConflictError, StaleDataError) as e:
        db.session.rollback()
        return create_response(
            success=False,
            message=t("api.item_conflict") if isinstance(e, StaleDataError) else str(e),
            redirect_url=url_for("inventory.inventory"),
            status_code=409,
        )
    except IntegrityError:
        db.session.rollback()
        return create_response(
            success=False,
            message=t("api.missing_fields"),
            redirect_url=url_for("inventory.inventory"),
            status_code=409,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error updating items")
        return create_response(
            success=False,
            message=t("common.error_generic"),
            redirect_url=url_for("inventory.inventory"),
            status_code=500,
        )


@inventory_bp.route("/remove_item/<int:item_id>", methods=["POST"])
def remove_item(item_id: int):
    """Remove an inventory item."""
    try:
        item = db.session.get(Item, item_id)
        if not item:
            return create_response(
                success=False,
                message=t("api.item_not_found"),
                redirect_url=url_for("inventory.inventory"),
                status_code=404,
            )

        _check_version(item, request.form.get("version"))
        item_name = item.name
        db.session.delete(item)
        db.session.commit()

        if is_ajax_request():
            return jsonify({"status": "success", "message": f"Artikel {item_name} borttagen"})
        return redirect(url_for("inventory.inventory"))
    except ValueError as e:
        db.session.rollback()
        return create_response(
            success=False,
            message=str(e),
            redirect_url=url_for("inventory.inventory"),
            status_code=400,
        )
    except (_ItemConflictError, StaleDataError) as e:
        db.session.rollback()
        return create_response(
            success=False,
            message=t("api.item_conflict") if isinstance(e, StaleDataError) else str(e),
            redirect_url=url_for("inventory.inventory"),
            status_code=409,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(f"Error removing item {item_id}")
        return create_response(
            success=False,
            message=t("common.error_generic"),
            redirect_url=url_for("inventory.inventory"),
            status_code=500,
        )


@inventory_bp.route("/toggle_visibility/<int:item_id>", methods=["POST"])
def toggle_visibility(item_id: int):
    """Toggle whether an item is visible on the Inventera and shopping list pages."""
    try:
        item = db.session.get(Item, item_id)
        if not item:
            return jsonify({"status": "error", "message": t("api.item_not_found")}), 404
        _check_version(item, request.form.get("version"))
        item.is_visible = not bool(item.is_visible)
        item.version = (item.version or 1) + 1
        db.session.commit()
        return jsonify(
            {
                "status": "success",
                "item_id": item.id,
                "is_visible": bool(item.is_visible),
                "version": item.version,
            }
        )
    except ValueError as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 400
    except (_ItemConflictError, StaleDataError) as e:
        db.session.rollback()
        return jsonify(
            {
                "status": "error",
                "message": t("api.item_conflict") if isinstance(e, StaleDataError) else str(e),
            }
        ), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(f"Error toggling visibility for {item_id}")
        return jsonify({"status": "error", "message": t("common.error_generic")}), 500
