"""Option management services (Unit, Location, Store)."""

import uuid
from typing import Any

from app.extensions import db
from app.integrations.home_assistant import get_store_todo_map, save_store_todo_map
from app.models.item import Item, Location, Store, Unit

OPTION_FIELDS = ("unit", "location", "store")
OptionModel = Unit | Location | Store
OPTION_MODELS: dict[str, type[Any]] = {
    "unit": Unit,
    "location": Location,
    "store": Store,
}


def get_distinct_field_values(field_name: str) -> list[str]:
    """Return sorted distinct non-empty values for a managed option field."""
    if field_name in OPTION_MODELS:
        model = OPTION_MODELS[field_name]
        return sorted((row.name for row in model.query.all()), key=str.casefold)
    return []


def get_or_create_option(field_name: str, name: str):
    """Fetch existing option row (Unicode case-insensitive) or stage a new one."""
    clean = (name or "").strip()
    if not clean:
        return None
    clean_cf = clean.casefold()
    model = OPTION_MODELS[field_name]
    existing = next((row for row in model.query.all() if row.name.casefold() == clean_cf), None)
    if existing:
        return existing
    created = model(name=clean)
    db.session.add(created)
    db.session.flush()
    return created


def get_managed_options(field_name: str):
    """Return all option rows (with .id and .name) for a field sorted by Unicode casefold."""
    model = OPTION_MODELS[field_name]
    return sorted(model.query.all(), key=lambda row: row.name.casefold())


def save_managed_options_crud(
    field_name: str,
    renames: dict[int, str],
    new_names: list[str],
    delete_ids: list[int],
) -> None:
    """
    Apply deletions, renames (supporting swaps without silent merges), and additions
    for Unit/Location/Store by ID and sync Items and store-todo mappings.
    """
    model = OPTION_MODELS[field_name]
    fk_col = f"{field_name}_id"
    delete_set = set(delete_ids)

    # 1. Validate final names across all surviving + new options before mutating
    all_rows = model.query.all()
    final_names: dict[str, str] = {}
    for row in all_rows:
        if row.id in delete_set:
            continue
        target_name = (renames[row.id] if row.id in renames else row.name).strip()
        if not target_name:
            raise ValueError(f"Option name for {field_name} cannot be empty")
        key = target_name.casefold()
        if key in final_names:
            raise ValueError(f"Duplicate {field_name} name: {target_name}")
        final_names[key] = target_name

    clean_new: list[str] = []
    for raw in new_names:
        clean = (raw or "").strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in final_names:
            raise ValueError(f"Duplicate {field_name} name: {clean}")
        final_names[key] = clean
        clean_new.append(clean)

    # 2. Apply deletions and track deleted store names for map cleanup
    deleted_store_names: set[str] = set()
    for opt_id in delete_set:
        opt = db.session.get(model, opt_id)
        if opt:
            if field_name == "unit" and Item.query.filter(Item.unit_id == opt.id).count() > 0:
                raise ValueError(f"Cannot delete unit '{opt.name}' while it is in use by items")
            if field_name == "store":
                deleted_store_names.add(opt.name)
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {fk_col: None, field_name: "", "version": Item.version + 1},
                synchronize_session=False,
            )
            db.session.delete(opt)
    db.session.flush()

    # 3. Apply renames via two-phase temporary names so swaps (A <-> B) never collide
    store_renames: dict[str, str] = {}
    pending_renames: list[tuple[OptionModel, str, str]] = []
    for opt_id, raw_new in renames.items():
        if opt_id in delete_set:
            continue
        clean = raw_new.strip()
        opt = db.session.get(model, opt_id)
        if not opt or opt.name == clean:
            continue
        pending_renames.append((opt, opt.name, clean))

    used_names = {row.name.casefold() for row in model.query.all()}
    for idx, (opt, _old, _new) in enumerate(pending_renames):
        tmp_name = f"__tmp_{opt.id}_{idx}_{uuid.uuid4().hex[:12]}"
        while tmp_name.casefold() in used_names:
            tmp_name = f"__tmp_{uuid.uuid4().hex[:24]}"
        used_names.add(tmp_name.casefold())
        opt.name = tmp_name
    db.session.flush()

    for opt, old_name, new_name in pending_renames:
        opt.name = new_name
        Item.query.filter(getattr(Item, fk_col) == opt.id).update(
            {field_name: new_name, "version": Item.version + 1}, synchronize_session=False
        )
        if field_name == "store":
            store_renames[old_name] = new_name

    # 4. Apply additions
    for clean in clean_new:
        get_or_create_option(field_name, clean)

    db.session.flush()

    # 5. Sync store -> todo.* mapping for renames and deletions
    if field_name == "store" and (store_renames or deleted_store_names):
        todo_map = get_store_todo_map()
        updated_map = dict(todo_map)
        changed = False
        for old_name in deleted_store_names:
            if old_name in updated_map:
                del updated_map[old_name]
                changed = True
        for old_name, new_name in store_renames.items():
            if old_name in todo_map:
                updated_map[new_name] = todo_map[old_name]
                if old_name not in store_renames.values():
                    updated_map.pop(old_name, None)
                changed = True
        if changed:
            save_store_todo_map(updated_map)
