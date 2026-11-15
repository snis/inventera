"""Deep regression tests for HA outage preservation, concurrency, swaps, XSS/URLs, and backup/restore."""

import io
import json
import threading
from unittest.mock import MagicMock, patch

import pytest
from flask_migrate import upgrade as alembic_upgrade
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.integrations.home_assistant import get_store_todo_map, save_store_todo_map
from app.models.item import Item, Store, Unit
from app.models.settings import Settings
from app.services.options import save_managed_options_crud
from app.services.shopping_sync import _is_item_present, sync_low_inventory_to_ha


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / "test.sqlite3"
    test_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
            "ENFORCE_INGRESS_PROXY": False,
        }
    )
    with test_app.app_context():
        alembic_upgrade()
        yield test_app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_settings_preserves_ha_mappings_when_ha_is_down(app, client, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        db.session.add(Store(name="ICA"))
        Settings.set("ha_default_todo_entity", "todo.default_list")
        save_store_todo_map({"ICA": "todo.ica_list"})
        db.session.commit()

    def fake_get(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 503
        return resp

    with patch("app.integrations.home_assistant.requests.get", side_effect=fake_get):
        page_html = client.get("/settings").get_data(as_text=True)
        assert "todo.default_list" in page_html
        assert "todo.ica_list" in page_html

        res = client.post(
            "/settings/save",
            data={
                "calendar_url": "https://cal.example.com",
                "ha_lists_available": "0",
                "ha_default_todo_entity": "todo.default_list",
                "store_map_ICA": "todo.ica_list",
            },
        )
        assert res.status_code == 302

    with app.app_context():
        assert Settings.get("ha_default_todo_entity") == "todo.default_list"
        assert get_store_todo_map() == {"ICA": "todo.ica_list"}
        assert Settings.get("calendar_url") == "https://cal.example.com"


def test_sqlite_foreign_keys_enabled_and_large_int_returns_400(app, client):
    with app.app_context():
        fk_status = db.session.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk_status == 1

    res = client.post(
        "/update_quantity",
        data={"item_id": "1", "new_quantity": "9223372036854775808"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 400


def test_concurrent_syncs_do_not_create_duplicates(app, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.add(
            Item(name="Salt", quantity=0, alert_quantity=1, unit="st", store="ICA", is_visible=True)
        )
        db.session.commit()

    ha_items: list[dict] = []
    ha_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def fake_post(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        if "get_items" in url:
            with ha_lock:
                snapshot = list(ha_items)
            resp.json.return_value = {"service_response": {"todo.shopping": {"items": snapshot}}}
        else:
            with ha_lock:
                ha_items.append({"summary": json["item"], "status": "needs_action"})
        return resp

    results: list[dict] = []

    def worker():
        with app.app_context():
            barrier.wait()
            results.append(sync_low_inventory_to_ha())

    with patch("app.integrations.home_assistant.requests.post", side_effect=fake_post):
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert len(ha_items) == 1
    assert sorted(r["synced_count"] for r in results) == [0, 1]


def test_options_swap_conflict_and_store_delete_cleanup(app):
    with app.app_context():
        s1 = Store(name="Alpha")
        s2 = Store(name="Beta")
        db.session.add_all([s1, s2])
        db.session.flush()
        save_store_todo_map({"Alpha": "todo.a", "Beta": "todo.b"})
        db.session.commit()
        id1, id2 = s1.id, s2.id

        # Swap Alpha <-> Beta cleanly
        save_managed_options_crud("store", {id1: "Beta", id2: "Alpha"}, [], [])
        db.session.commit()
        assert db.session.get(Store, id1).name == "Beta"
        assert db.session.get(Store, id2).name == "Alpha"
        assert get_store_todo_map() == {"Beta": "todo.a", "Alpha": "todo.b"}

        # Duplicate conflict must raise ValueError without merging
        with pytest.raises(ValueError):
            save_managed_options_crud("store", {id1: "Alpha"}, [], [])
        db.session.rollback()

        # Deleting a store removes its todo mapping
        save_managed_options_crud("store", {}, [], [id1])
        db.session.commit()
        assert "Beta" not in get_store_todo_map()
        assert get_store_todo_map() == {"Alpha": "todo.b"}


def test_ha_malformed_200_empty_dict_and_unmapped_errors(app, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.add(
            Item(name="Smör", quantity=0, alert_quantity=1, unit="st", store="ICA", is_visible=True)
        )
        db.session.commit()

        def fake_post_malformed(url, headers=None, json=None, timeout=None):
            if "add_item" in url:
                raise AssertionError("add_item must not run when get_items returns {}")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {}
            return resp

        with patch(
            "app.integrations.home_assistant.requests.post", side_effect=fake_post_malformed
        ):
            res = sync_low_inventory_to_ha()
        assert res["status"] == "error"
        assert res["failed_count"] == 1

    # All unmapped items -> status == "error"
    with app.app_context():
        Settings.set("ha_default_todo_entity", "")
        db.session.commit()
        with patch("app.integrations.home_assistant.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
            res_unmapped = sync_low_inventory_to_ha()
        assert res_unmapped["status"] == "error"
        assert res_unmapped["unmapped_count"] == 1


def test_salt_does_not_match_salt_fint_with_parens():
    assert _is_item_present("Salt", ["salt (fint) (0 st)"]) is False
    assert _is_item_present("Salt", ["salt (fint)"]) is False
    assert _is_item_present("Salt", ["salt (0 st)"]) is True
    assert _is_item_present("Salt (fint)", ["salt (fint) (0 st)"]) is True
    assert _is_item_present("Salt (fint)", ["salt (fint)"]) is True


@given(
    name=st.text(min_size=1, max_size=20).filter(
        lambda s: s.strip() != "" and "(" not in s and ")" not in s
    )
)
@settings(max_examples=30)
def test_hypothesis_different_suffix_never_collides(name):
    other = f"{name.strip()} (extra) (1 st)".casefold()
    assert _is_item_present(name, [other]) is False


def test_calendar_url_rejects_javascript_and_accepts_https(app, client):
    res_bad = client.post("/settings/save", data={"calendar_url": "javascript:alert(1)"})
    assert res_bad.status_code == 400

    res_ok = client.post("/settings/save", data={"calendar_url": "https://calendar.example.com"})
    assert res_ok.status_code == 302
    with app.app_context():
        assert Settings.get("calendar_url") == "https://calendar.example.com"


def test_backup_export_and_atomic_restore(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add(
            Item(
                name="Kaffe",
                quantity=3,
                alert_quantity=1,
                unit="st",
                unit_id=u.id,
                location="Skafferi",
                store="ICA",
                is_visible=False,
            )
        )
        Settings.set("ha_token", "secret-should-not-export")
        Settings.set("calendar_url", "https://cal.example.com")
        db.session.commit()

    dl = client.get("/settings/backup")
    assert dl.status_code == 200
    backup_data = json.loads(dl.get_data(as_text=True))
    assert "ha_token" not in backup_data["settings"]
    assert backup_data["items"][0]["name"] == "Kaffe"
    assert backup_data["items"][0]["is_visible"] is False

    # Reject invalid JSON, XSS calendar_url, float quantity, string bool, unknown version
    invalid_payloads = [
        b"{not-json",
        json.dumps({**backup_data, "settings": {"calendar_url": "javascript:alert(1)"}}).encode(
            "utf-8"
        ),
        json.dumps(
            {
                **backup_data,
                "items": [{**backup_data["items"][0], "quantity": 1.9}],
            }
        ).encode("utf-8"),
        json.dumps(
            {
                **backup_data,
                "items": [{**backup_data["items"][0], "is_visible": "false"}],
            }
        ).encode("utf-8"),
        json.dumps({"version": "9.9", "items": []}).encode("utf-8"),
        json.dumps({**backup_data, "settings": {"ha_store_todo_map": {"ICA": 123}}}).encode(
            "utf-8"
        ),
    ]
    for payload_bytes in invalid_payloads:
        bad_restore = client.post(
            "/settings/restore",
            data={"backup_file": (io.BytesIO(payload_bytes), "bad.json")},
            content_type="multipart/form-data",
        )
        assert bad_restore.status_code == 400
        with app.app_context():
            assert Item.query.filter_by(name="Kaffe").count() == 1

    # Valid restore replaces data cleanly
    backup_data["items"] = [
        {
            "name": "Te",
            "quantity": 5,
            "alert_quantity": 2,
            "unit": "pkt",
            "location": "Skafferi",
            "store": "Coop",
            "is_visible": True,
        }
    ]
    good_restore = client.post(
        "/settings/restore",
        data={
            "backup_file": (io.BytesIO(json.dumps(backup_data).encode("utf-8")), "backup.json"),
        },
        content_type="multipart/form-data",
    )
    assert good_restore.status_code == 302
    with app.app_context():
        assert Item.query.filter_by(name="Kaffe").count() == 0
        te = Item.query.filter_by(name="Te").first()
        assert te is not None
        assert te.unit_id is not None
        assert te.store == "Coop"


def test_backup_roundtrip_case_variant_names_empty_unit_and_tz_conversion(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add_all(
            [
                Item(name="Salt", quantity=1, alert_quantity=0, unit="st", unit_id=u.id),
                Item(name="salt", quantity=2, alert_quantity=0, unit="", unit_id=None),
            ]
        )
        db.session.commit()

    dl = client.get("/settings/backup")
    assert dl.status_code == 200
    payload = json.loads(dl.get_data(as_text=True))
    payload["items"][0]["last_checked"] = "2026-11-15T15:00:00+02:00"

    res = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "b.json")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app.app_context():
        big = Item.query.filter_by(name="Salt").first()
        small = Item.query.filter_by(name="salt").first()
        assert big is not None and small is not None
        assert small.unit == "" and small.unit_id is None
        assert big.last_checked.hour == 13
        assert big.last_checked.minute == 0


def test_cannot_delete_unit_in_use_and_settings_confirm_attr_valid(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add(Item(name="Pasta", quantity=1, alert_quantity=1, unit="st", unit_id=u.id))
        db.session.commit()
        unit_id = u.id

        with pytest.raises(ValueError):
            save_managed_options_crud("unit", {}, [], [unit_id])
        db.session.rollback()

    html = client.get("/settings").get_data(as_text=True)
    assert 'id="restore-backup-form"' in html
    assert "data-confirm=" in html
    assert 'onsubmit="return confirm(' not in html
