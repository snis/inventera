"""Option management services (Unit, Location, Store)."""

from app.extensions import db
from app.integrations.home_assistant import get_store_todo_map, save_store_todo_map
from app.models.item import Item, Location, Store, Unit

OPTION_FIELDS = ("unit", "location", "store")
OPTION_MODELS = {
    "unit": Unit,
    "location": Location,
    "store": Store,
}


def get_distinct_field_values(field_name: str) -> list[str]:
    """Return sorted distinct non-empty values for a managed option field."""
    if field_name in OPTION_MODELS:
        model = OPTION_MODELS[field_name]
        return [row.name for row in model.query.order_by(db.func.lower(model.name)).all()]
    return []


def get_or_create_option(field_name: str, name: str):
    """Fetch existing option row (case-insensitive) or stage a new one."""
    clean = (name or "").strip()
    if not clean:
        return None
    model = OPTION_MODELS[field_name]
    existing = model.query.filter(db.func.lower(model.name) == clean.lower()).first()
    if existing:
        return existing
    created = model(name=clean)
    db.session.add(created)
    db.session.flush()
    return created


def get_managed_options(field_name: str):
    """Return all option rows (with .id and .name) for a field sorted by name."""
    model = OPTION_MODELS[field_name]
    return model.query.order_by(db.func.lower(model.name)).all()


def save_managed_options_crud(
    field_name: str,
    renames: dict[int, str],
    new_names: list[str],
    delete_ids: list[int],
) -> None:
    """Apply renames, additions, and deletions for Unit/Location/Store by ID and sync Items."""
    model = OPTION_MODELS[field_name]
    fk_col = f"{field_name}_id"

    for opt_id in delete_ids:
        opt = db.session.get(model, opt_id)
        if opt:
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {fk_col: None, field_name: ""}, synchronize_session=False
            )
            db.session.delete(opt)
    db.session.flush()

    store_renames: dict[str, str] = {}
    for opt_id, new_name in renames.items():
        clean = (new_name or "").strip()
        if not clean:
            continue
        opt = db.session.get(model, opt_id)
        if not opt or opt.name == clean:
            continue
        conflict = model.query.filter(
            db.func.lower(model.name) == clean.lower(), model.id != opt.id
        ).first()
        if conflict:
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {fk_col: conflict.id, field_name: conflict.name}, synchronize_session=False
            )
            if field_name == "store":
                store_renames[opt.name] = conflict.name
            db.session.delete(opt)
        else:
            old_name = opt.name
            opt.name = clean
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {field_name: clean}, synchronize_session=False
            )
            if field_name == "store":
                store_renames[old_name] = clean

    for name in new_names:
        get_or_create_option(field_name, name)

    db.session.flush()

    if store_renames:
        todo_map = get_store_todo_map()
        changed = False
        for old_name, new_name in store_renames.items():
            if old_name in todo_map:
                if new_name not in todo_map:
                    todo_map[new_name] = todo_map[old_name]
                del todo_map[old_name]
                changed = True
        if changed:
            save_store_todo_map(todo_map)
