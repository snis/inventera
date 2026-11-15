"""Tests for validation/HTTP error contract, CSRF protection, and Alembic migrations."""

import re
import sqlite3
from unittest.mock import patch

import pytest
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import inspect

from app import create_app, db
from app.models.item import Item, Location, Store, Unit


@pytest.fixture()
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "ENFORCE_INGRESS_PROXY": False,
        }
    )
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_update_quantity_returns_400_for_invalid_and_404_for_missing(client):
    res_bad = client.post(
        "/update_quantity",
        data={"item_id": "1", "new_quantity": "abc"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_bad.status_code == 400
    assert res_bad.get_json()["status"] == "error"

    res_missing = client.post(
        "/update_quantity",
        data={"item_id": "999", "new_quantity": "5"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_missing.status_code == 404
    assert res_missing.get_json()["status"] == "error"


def test_update_items_validation_400_404_409(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Mjölk", quantity=2, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id, unit_id = item.id, u.id

    # Invalid quantity -> 400 and quantity must remain 2
    res_bad = client.post(
        "/update_items",
        data={
            f"update_item_{item_id}": str(item_id),
            f"name_{item_id}": "Mjölk",
            f"quantity_{item_id}": "not-a-number",
            f"alert_quantity_{item_id}": "1",
            f"unit_{item_id}": str(unit_id),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_bad.status_code == 400
    with app.app_context():
        assert db.session.get(Item, item_id).quantity == 2

    # Nonexistent item -> 404
    res_missing = client.post(
        "/update_items",
        data={"update_item_999": "999"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_missing.status_code == 404

    # Duplicate item name -> 409
    res_dup = client.post(
        "/update_items",
        data={
            "add_item": "1",
            "new_name": "Mjölk",
            "new_quantity": "1",
            "new_alert_quantity": "1",
            "new_unit": str(unit_id),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_dup.status_code == 409


def test_remove_item_404_when_missing(client):
    res = client.post("/remove_item/999", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 404


def test_index_returns_500_instead_of_empty_list_on_db_error(client):
    with patch("app.controllers.main.get_items_by_location", side_effect=RuntimeError("db down")):
        res = client.get("/")
    assert res.status_code == 500


def test_csrf_protection_blocks_missing_token_and_accepts_valid_token():
    csrf_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "ENFORCE_INGRESS_PROXY": False,
        }
    )
    with csrf_app.app_context():
        db.create_all()
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Kaffe", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    csrf_client = csrf_app.test_client()

    # Missing CSRF token -> 400
    res_blocked = csrf_client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "3"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_blocked.status_code == 400

    # Valid CSRF token from meta tag -> 200
    html = csrf_client.get("/").get_data(as_text=True)
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    token = match.group(1)

    res_ok = csrf_client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "3"},
        headers={"X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token},
    )
    assert res_ok.status_code == 200
    assert res_ok.get_json()["new_quantity"] == 3


def test_alembic_fresh_install_and_legacy_upgrade(tmp_path):
    # 1. Fresh install
    fresh_db = tmp_path / "fresh.sqlite3"
    fresh_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{fresh_db}",
            "ENFORCE_INGRESS_PROXY": False,
        }
    )
    with fresh_app.app_context():
        alembic_upgrade()
        tables = set(inspect(db.engine).get_table_names())
        assert {"item", "settings", "units", "locations", "stores", "alembic_version"} <= tables

    # 2. Legacy v1 DB upgrade + backfill
    legacy_db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(legacy_db)
    conn.execute(
        """
        CREATE TABLE item (
            id INTEGER PRIMARY KEY,
            name VARCHAR(64) NOT NULL UNIQUE,
            quantity INTEGER NOT NULL DEFAULT 0,
            alert_quantity INTEGER NOT NULL DEFAULT 0,
            unit VARCHAR(16) NOT NULL,
            category VARCHAR(32) NOT NULL DEFAULT '',
            location VARCHAR(64) NOT NULL DEFAULT '',
            store VARCHAR(64) NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            key VARCHAR(64) NOT NULL UNIQUE,
            value TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO item (name, quantity, alert_quantity, unit, location, store) "
        "VALUES ('Tvål', 2, 1, 'flaskor', 'Badrum', 'Apoteket')"
    )
    conn.commit()
    conn.close()

    legacy_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{legacy_db}",
            "ENFORCE_INGRESS_PROXY": False,
        }
    )
    with legacy_app.app_context():
        alembic_upgrade()
        item = Item.query.filter_by(name="Tvål").first()
        assert item is not None
        assert item.is_visible is True
        assert item.unit_id is not None
        assert item.location_id is not None
        assert item.store_id is not None
        assert Unit.query.filter_by(name="flaskor").first() is not None
        assert Location.query.filter_by(name="Badrum").first() is not None
        assert Store.query.filter_by(name="Apoteket").first() is not None
