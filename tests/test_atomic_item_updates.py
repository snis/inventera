"""Regression checks for writes that race after a request has read an item."""

from unittest.mock import patch

import pytest
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app import create_app
from app.controllers.inventory import _check_version
from app.extensions import db
from app.models.item import Item, Location, Store, Unit
from app.services.options import save_managed_options_crud


@pytest.fixture()
def app(tmp_path):
    with patch("app.config.get_or_create_secret_key", return_value="isolated-test-key"):
        app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "ENFORCE_INGRESS_PROXY": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'inventory.sqlite3'}",
            }
        )
    with app.app_context():
        upgrade()
        yield app
        db.session.remove()
        db.engine.dispose()


def seed_item():
    item = Item(name="Salt", quantity=1, alert_quantity=0, unit="")
    db.session.add(item)
    db.session.commit()
    return item.id


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_database_rejects_write_from_stale_session(app, operation):
    item_id = seed_item()
    with Session(db.engine) as first, Session(db.engine) as second:
        current = first.get(Item, item_id)
        stale = second.get(Item, item_id)
        current.quantity = 7
        current.version += 1
        first.commit()

        if operation == "update":
            stale.quantity = 99
            stale.version += 1
        else:
            second.delete(stale)
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()

    db.session.expire_all()
    assert db.session.get(Item, item_id).quantity == 7


@pytest.mark.parametrize("operation", ["quantity", "item", "delete", "visibility"])
def test_http_write_returns_conflict_if_item_changes_after_version_check(app, operation):
    item_id = seed_item()

    def concurrent_write(item, version):
        _check_version(item, version)
        with Session(db.engine) as other:
            current = other.get(Item, item.id)
            current.quantity = 7
            current.version += 1
            other.commit()

    routes = {
        "quantity": ("/update_quantity", {"item_id": item_id, "new_quantity": 99}),
        "item": (
            "/update_items",
            {
                "update_item": item_id,
                f"version_{item_id}": 1,
                f"name_{item_id}": "Renamed",
                f"quantity_{item_id}": 99,
                f"alert_quantity_{item_id}": 0,
            },
        ),
        "delete": (f"/remove_item/{item_id}", {}),
        "visibility": (f"/toggle_visibility/{item_id}", {}),
    }
    url, data = routes[operation]
    with patch("app.controllers.inventory._check_version", side_effect=concurrent_write):
        response = app.test_client().post(
            url,
            data={**data, "version": 1},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    assert response.status_code == 409
    assert response.json["status"] == "error"
    assert "UPDATE statement" not in response.json["message"]
    db.session.expire_all()
    item = db.session.get(Item, item_id)
    assert (item.name, item.quantity, item.version, item.is_visible) == ("Salt", 7, 2, True)


@pytest.mark.parametrize("names", [("Salt", "sALT"), ("Örtsalt", "ÖRTSALT"), ("Straße", "STRASSE")])
def test_database_enforces_unicode_name_uniqueness(app, names):
    # Both inserts are prepared before either writer commits, bypassing HTTP prechecks.
    with Session(db.engine) as first, Session(db.engine) as second:
        first.add(Item(name=names[0], quantity=1, alert_quantity=0, unit=""))
        second.add(Item(name=names[1], quantity=1, alert_quantity=0, unit=""))
        first.commit()
        with pytest.raises(IntegrityError):
            second.commit()
        second.rollback()

    assert Item.query.count() == 1


@pytest.mark.parametrize("field,model", [("unit", Unit), ("location", Location), ("store", Store)])
def test_option_rename_invalidates_open_item_forms(app, field, model):
    option = model(name="Old")
    db.session.add(option)
    db.session.flush()
    item = Item(name="Salt", quantity=1, alert_quantity=0, unit="")
    setattr(item, field, option.name)
    setattr(item, f"{field}_id", option.id)
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    save_managed_options_crud(field, {option.id: "New"}, [], [])
    db.session.commit()
    response = app.test_client().post(
        "/update_quantity",
        data={"item_id": item_id, "new_quantity": 99, "version": 1},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 409
    db.session.expire_all()
    assert getattr(db.session.get(Item, item_id), field) == "New"
