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
from app.models.item import Item, Location, Store, Unit
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


def test_backup_roundtrip_empty_unit_tz_and_case_duplicate_rejected(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add_all(
            [
                Item(name="Salt", quantity=1, alert_quantity=0, unit="st", unit_id=u.id),
                Item(name="Peppar", quantity=2, alert_quantity=0, unit="", unit_id=None),
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
        salt = Item.query.filter_by(name="Salt").first()
        peppar = Item.query.filter_by(name="Peppar").first()
        assert salt is not None and peppar is not None
        assert peppar.unit == "" and peppar.unit_id is None
        assert salt.last_checked.hour == 13
        assert salt.last_checked.minute == 0

        # Backup with case-variant duplicate ("Salt" and "salt") must be rejected
        dup_payload = dict(payload)
        dup_payload["items"] = [
            payload["items"][0],
            {**payload["items"][1], "name": "salt"},
        ]
        from app.services.backup import restore_backup_payload

        with pytest.raises(ValueError, match="Duplicate item name"):
            restore_backup_payload(dup_payload)


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


def test_inventory_pagination_0_50_51_and_last_page(app, client):
    # 0 items
    assert client.get("/inventory").status_code == 200

    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        for i in range(50):
            db.session.add(
                Item(name=f"Artikel {i:02d}", quantity=1, alert_quantity=0, unit="st", unit_id=u.id)
            )
        db.session.commit()

    # 50 items (1 page)
    assert client.get("/inventory").status_code == 200

    with app.app_context():
        u = Unit.query.first()
        db.session.add(
            Item(name="Artikel 50", quantity=1, alert_quantity=0, unit="st", unit_id=u.id)
        )
        db.session.commit()

    # 51 items (2 pages)
    res_p1 = client.get("/inventory/1")
    res_p2 = client.get("/inventory/2")
    assert res_p1.status_code == 200
    assert res_p2.status_code == 200
    assert "Sida 2 av 2" in res_p2.get_data(as_text=True)


def test_ingress_data_url_not_corrupted_by_zero_in_token(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(id=7, name="Mjölk", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()

    html = client.get(
        "/inventory",
        headers={"X-Ingress-Path": "/api/hassio_ingress/abc0xyz"},
    ).get_data(as_text=True)
    assert 'data-url="/api/hassio_ingress/abc0xyz/toggle_visibility/7"' in html
    assert 'data-url="/api/hassio_ingress/abc0xyz/remove_item/7"' in html
    assert ".replace('0'" not in html


def test_swedish_unicode_locations_and_stores_backup_roundtrip(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add_all(
            [
                Item(
                    name="Lampor",
                    quantity=2,
                    alert_quantity=1,
                    unit="st",
                    unit_id=u.id,
                    location="Övervåning",
                    store="ÖoB",
                ),
                Item(
                    name="Påsar",
                    quantity=5,
                    alert_quantity=2,
                    unit="st",
                    unit_id=u.id,
                    location="Återvinning",
                    store="ÖoB",
                ),
            ]
        )
        db.session.commit()

    dl = client.get("/settings/backup")
    assert dl.status_code == 200
    payload = json.loads(dl.get_data(as_text=True))
    # Simulate mixed-case Swedish option list + item values
    payload["locations"] = ["övervåning", "återvinning"]
    payload["stores"] = ["öob"]

    res = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "se.json")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302


def test_huge_option_id_returns_400_and_settings_error_returns_500(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Ost", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    res = client.post(
        "/update_items",
        data={
            f"update_item_{item_id}": str(item_id),
            f"name_{item_id}": "Ost",
            f"quantity_{item_id}": "1",
            f"alert_quantity_{item_id}": "1",
            f"unit_{item_id}": str(10**40),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 400

    with patch("app.controllers.settings.get_ha_config", side_effect=RuntimeError("boom")):
        res_500 = client.get("/settings")
    assert res_500.status_code == 500


def test_metadata_rename_preserves_last_checked_date(app, client):
    from datetime import datetime

    old_dt = datetime(2020, 5, 1, 12, 0, 0)
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(
            name="GammaltNamn",
            quantity=3,
            alert_quantity=1,
            unit="st",
            unit_id=u.id,
            last_checked=old_dt,
        )
        db.session.add(item)
        db.session.commit()
        item_id, unit_id = item.id, u.id

    res = client.post(
        "/update_items",
        data={
            f"update_item_{item_id}": str(item_id),
            f"name_{item_id}": "NyttNamn",
            f"quantity_{item_id}": "3",
            f"alert_quantity_{item_id}": "1",
            f"unit_{item_id}": str(unit_id),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 200
    with app.app_context():
        updated = db.session.get(Item, item_id)
        assert updated.name == "NyttNamn"
        assert updated.last_checked == old_dt


def test_deleted_item_id_not_reused_and_stale_version_returns_409(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item_a = Item(name="Artikel A", quantity=2, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item_a)
        db.session.commit()
        id_a = item_a.id
        db.session.delete(item_a)
        db.session.commit()

        item_b = Item(name="Artikel B", quantity=5, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item_b)
        db.session.commit()
        id_b = item_b.id

    assert id_b != id_a

    # Stale form targeting deleted Artikel A must return 404 and not touch Artikel B
    res_deleted = client.post(
        "/update_quantity",
        data={"item_id": str(id_a), "new_quantity": "99", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_deleted.status_code == 404

    # First update on Artikel B with version=1 succeeds and bumps version to 2
    res_ok = client.post(
        "/update_quantity",
        data={"item_id": str(id_b), "new_quantity": "7", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_ok.status_code == 200
    assert res_ok.get_json()["version"] == 2

    # Stale update with version=1 must return 409 and preserve quantity=7
    res_stale = client.post(
        "/update_quantity",
        data={"item_id": str(id_b), "new_quantity": "99", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_stale.status_code == 409

    with app.app_context():
        b_now = db.session.get(Item, id_b)
        assert b_now.quantity == 7
        assert b_now.version == 2


def test_backup_restore_clears_omitted_settings_while_preserving_ha_token(app, client):
    dl = client.get("/settings/backup")
    assert dl.status_code == 200
    empty_backup = json.loads(dl.get_data(as_text=True))
    empty_backup["settings"] = {}

    with app.app_context():
        Settings.set("ha_token", "secret-token-keep")
        Settings.set("calendar_url", "https://example.com/cal")
        Settings.set("ha_default_todo_entity", "todo.shopping")
        Settings.set("ha_store_todo_map", '{"ICA": "todo.ica"}')
        db.session.commit()

    res = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(json.dumps(empty_backup).encode("utf-8")), "empty.json")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app.app_context():
        assert Settings.get("calendar_url") == ""
        assert Settings.get("ha_default_todo_entity") == ""
        assert Settings.get("ha_store_todo_map") == "{}"
        assert Settings.get("ha_token") == "secret-token-keep"


def test_case_insensitive_item_uniqueness_across_create_and_rename(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add_all(
            [
                Item(name="Salt", quantity=1, alert_quantity=0, unit="st", unit_id=u.id),
                Item(name="Socker", quantity=1, alert_quantity=0, unit="st", unit_id=u.id),
            ]
        )
        db.session.commit()
        unit_id = u.id
        socker_id = Item.query.filter_by(name="Socker").first().id

    # Creating "salt" or "sAlt" must fail with 409
    for variant in ("salt", "sAlt"):
        res_create = client.post(
            "/update_items",
            data={
                "add_item": "true",
                "new_name": variant,
                "new_quantity": "1",
                "new_alert_quantity": "0",
                "new_unit": str(unit_id),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert res_create.status_code == 409

    # Renaming "Socker" -> "sAlt" must also fail with 409
    res_rename = client.post(
        "/update_items",
        data={
            f"update_item_{socker_id}": str(socker_id),
            f"name_{socker_id}": "sAlt",
            f"quantity_{socker_id}": "1",
            f"alert_quantity_{socker_id}": "0",
            f"unit_{socker_id}": str(unit_id),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_rename.status_code == 409


def test_index_renders_save_sequencing_and_version_attr(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add(Item(name="Smör", quantity=2, alert_quantity=1, unit="st", unit_id=u.id))
        db.session.commit()

    html = client.get("/").get_data(as_text=True)
    assert 'data-version="1"' in html
    assert "saveSeq" in html
    assert "inFlightSave" in html


def test_ha_sync_empty_unit_and_parenthesized_unit_no_duplicates(app):
    with app.app_context():
        u_paren = Unit(name="förp (10 st)")
        u_st = Unit(name="st")
        db.session.add_all([u_paren, u_st])
        db.session.flush()
        db.session.add_all(
            [
                Item(name="Salt", quantity=0, alert_quantity=1, unit="", unit_id=None),
                Item(
                    name="Pasta",
                    quantity=1,
                    alert_quantity=2,
                    unit="förp (10 st)",
                    unit_id=u_paren.id,
                ),
                Item(
                    name="Vatten (500 ml)",
                    quantity=0,
                    alert_quantity=1,
                    unit="st",
                    unit_id=u_st.id,
                ),
            ]
        )
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "tok")
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.commit()

        ha_items: list[str] = []

        def fake_get_existing(_self, _entity_id):
            return [s.casefold() for s in ha_items]

        def fake_add(_self, _entity_id, title, _desc):
            ha_items.append(title)
            return True

        with (
            patch(
                "app.services.shopping_sync.HomeAssistantTodoClient.get_existing_items",
                fake_get_existing,
            ),
            patch(
                "app.services.shopping_sync.HomeAssistantTodoClient.add_todo_item",
                fake_add,
            ),
        ):
            first = sync_low_inventory_to_ha()
            assert first["synced_count"] == 3
            assert "Salt (0)" in ha_items
            assert "Pasta (1 förp (10 st))" in ha_items
            assert "Vatten (500 ml) (0 st)" in ha_items

            second = sync_low_inventory_to_ha()
            assert second["synced_count"] == 0
            assert second["skipped_count"] == 3
            assert len(ha_items) == 3


def test_index_uses_safe_localstorage_wrappers(app, client):
    html = client.get("/").get_data(as_text=True)
    assert "safeStorageGet('collapsed_'" in html
    assert "safeStorageSet('collapsed_'" in html
    assert "localStorage.getItem('collapsed_" not in html
    assert "localStorage.setItem('collapsed_" not in html


def test_set_language_rejects_external_referrer(app, client):
    ext = client.get("/set_language/en", headers={"Referer": "https://evil.example/phish"})
    assert ext.status_code == 302
    assert ext.headers["Location"] == "/index"

    same = client.get("/set_language/sv", headers={"Referer": "http://localhost/inventory"})
    assert same.status_code == 302
    assert same.headers["Location"] == "http://localhost/inventory"


def test_ha_sync_distinguishes_batteri_and_batteri_4_st_by_item_id(app):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item1 = Item(name="Batteri", quantity=4, alert_quantity=5, unit="st", unit_id=u.id)
        item2 = Item(name="Batteri (4 st)", quantity=0, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add_all([item1, item2])
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "tok")
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.commit()
        id1, id2 = item1.id, item2.id

        ha_store: list[dict[str, str]] = []

        class FakeResp:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

        def fake_post(url, headers=None, json=None, timeout=5):
            if "todo/get_items" in url:
                return FakeResp(200, {"service_response": {"todo.shopping": {"items": ha_store}}})
            if "todo/add_item" in url:
                ha_store.append(
                    {
                        "uid": f"uid-{len(ha_store) + 1}",
                        "summary": json["item"],
                        "description": json.get("description", ""),
                        "status": "needs_action",
                    }
                )
                return FakeResp(200, {})
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("app.integrations.home_assistant.requests.post", fake_post):
            first = sync_low_inventory_to_ha()
            assert first["synced_count"] == 2
            assert len(ha_store) == 2
            assert f"[inventera_id:{id1}]" in ha_store[0]["description"]
            assert f"[inventera_id:{id2}]" in ha_store[1]["description"]

            second = sync_low_inventory_to_ha()
            assert second["synced_count"] == 0
            assert second["skipped_count"] == 2
            assert db.session.get(Item, id1).task_id == "uid-1"
            assert db.session.get(Item, id2).task_id == "uid-2"


def test_index_location_storage_key_is_stable_across_reordering(app, client):
    with app.app_context():
        u = Unit(name="st")
        loc_forrad = Location(name="Förråd")
        db.session.add_all([u, loc_forrad])
        db.session.flush()
        db.session.add(
            Item(
                name="Skruv",
                quantity=1,
                alert_quantity=0,
                unit="st",
                unit_id=u.id,
                location="Förråd",
                location_id=loc_forrad.id,
            )
        )
        db.session.commit()
        forrad_id = loc_forrad.id

    html_before = client.get("/").get_data(as_text=True)
    assert f'data-target="content-1" data-storage-key="loc-{forrad_id}"' in html_before

    with app.app_context():
        u = Unit.query.first()
        loc_badrum = Location(name="Badrum")
        db.session.add(loc_badrum)
        db.session.flush()
        db.session.add(
            Item(
                name="Tvål",
                quantity=1,
                alert_quantity=0,
                unit="st",
                unit_id=u.id,
                location="Badrum",
                location_id=loc_badrum.id,
            )
        )
        db.session.commit()
        badrum_id = loc_badrum.id

    html_after = client.get("/").get_data(as_text=True)
    assert f'data-target="content-1" data-storage-key="loc-{badrum_id}"' in html_after
    assert f'data-target="content-2" data-storage-key="loc-{forrad_id}"' in html_after


def test_backup_restore_preserves_item_id_and_task_id_prevents_ha_duplicates(app, client):
    ha_store: list[dict[str, str]] = []

    class FakeResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, headers=None, json=None, timeout=5):
        if "todo/get_items" in url:
            return FakeResp(200, {"service_response": {"todo.shopping": {"items": ha_store}}})
        if "todo/add_item" in url:
            ha_store.append(
                {
                    "uid": f"uid-{len(ha_store) + 1}",
                    "summary": json["item"],
                    "description": json.get("description", ""),
                    "status": "needs_action",
                }
            )
            return FakeResp(200, {})
        raise AssertionError(f"Unexpected URL: {url}")

    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        salt = Item(name="Salt", quantity=0, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(salt)
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "tok")
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.commit()
        original_id = salt.id

        with patch("app.integrations.home_assistant.requests.post", fake_post):
            first = sync_low_inventory_to_ha()
            assert first["synced_count"] == 1

    # Export and restore backup right after first sync (when task_id is not yet cached)
    dl = client.get("/settings/backup")
    assert dl.status_code == 200
    backup_bytes = dl.get_data()

    res = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(backup_bytes), "backup.json")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app.app_context():
        restored = Item.query.filter_by(name="Salt").first()
        assert restored is not None
        assert restored.id == original_id

        with patch("app.integrations.home_assistant.requests.post", fake_post):
            second = sync_low_inventory_to_ha()
            assert second["synced_count"] == 0
            assert second["skipped_count"] == 1
            assert len(ha_store) == 1


def test_deleted_store_location_unit_id_not_reused_by_sqlite(app, client):
    with app.app_context():
        for model, old_name, new_name in (
            (Store, "OldStore", "NewStore"),
            (Location, "OldLoc", "NewLoc"),
            (Unit, "OldUnit", "NewUnit"),
        ):
            first = model(name=old_name)
            db.session.add(first)
            db.session.commit()
            old_id = first.id
            db.session.delete(first)
            db.session.commit()

            second = model(name=new_name)
            db.session.add(second)
            db.session.commit()
            assert second.id != old_id
            if model is Store:
                deleted_store_id = old_id
                new_store_id = second.id

    # Stale settings form targeting deleted_store_id must not rename NewStore
    res = client.post(
        "/settings/save",
        data={"action": "save_stores", f"rename_store_{deleted_store_id}": "Hijacked"},
    )
    assert res.status_code == 302
    with app.app_context():
        assert db.session.get(Store, new_store_id).name == "NewStore"


def test_options_rename_succeeds_even_when_tmp_rename_name_exists(app):
    with app.app_context():
        u1 = Unit(name="st")
        u2 = Unit(name="kg")
        u_collision = Unit(name="__tmp_rename_1_0__")
        db.session.add_all([u1, u2, u_collision])
        db.session.commit()

        save_managed_options_crud(
            "unit",
            {u1.id: "kg", u2.id: "st"},
            [],
            [],
        )
        db.session.commit()

        assert db.session.get(Unit, u1.id).name == "kg"
        assert db.session.get(Unit, u2.id).name == "st"
        assert db.session.get(Unit, u_collision.id).name == "__tmp_rename_1_0__"


def test_backup_restore_invalidates_stale_item_versions(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Kaffe", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    res_bump = client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "9", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_bump.status_code == 200
    assert res_bump.get_json()["version"] == 2

    backup_bytes = client.get("/settings/backup").get_data()
    res_restore = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(backup_bytes), "v2.json")},
        content_type="multipart/form-data",
    )
    assert res_restore.status_code == 302

    # Both version=1 and version=2 forms from before restore must now fail with 409
    for old_ver in ("1", "2"):
        res_del = client.post(
            f"/remove_item/{item_id}",
            data={"version": old_ver},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert res_del.status_code == 409

    with app.app_context():
        restored = db.session.get(Item, item_id)
        assert restored is not None
        assert restored.version >= 3


def test_store_swap_with_unmapped_partner_does_not_duplicate_todo_mapping(app):
    with app.app_context():
        alpha = Store(name="Alpha")
        beta = Store(name="Beta")
        db.session.add_all([alpha, beta])
        db.session.flush()
        save_store_todo_map({"Alpha": "todo.alpha"})
        db.session.commit()

        save_managed_options_crud(
            "store",
            {alpha.id: "Beta", beta.id: "Alpha"},
            [],
            [],
        )
        db.session.commit()

        assert get_store_todo_map() == {"Beta": "todo.alpha"}


def test_queued_ha_sync_rereads_updated_stock_after_waiting_on_lock(app):
    from app.services import shopping_sync

    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        salt = Item(name="Salt", quantity=1, alert_quantity=2, unit="st", unit_id=u.id)
        db.session.add(salt)
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "tok")
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.commit()
        salt_id = salt.id

    results: list[dict] = []
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_lock():
        with shopping_sync._sync_lock:
            lock_acquired.set()
            release_lock.wait(timeout=5)

    def run_queued_sync():
        with app.app_context():
            with (
                patch(
                    "app.services.shopping_sync.HomeAssistantTodoClient.get_existing_items",
                    return_value=[],
                ),
                patch(
                    "app.services.shopping_sync.HomeAssistantTodoClient.add_todo_item",
                    return_value=True,
                ),
            ):
                results.append(sync_low_inventory_to_ha())

    t_holder = threading.Thread(target=hold_lock)
    t_holder.start()
    assert lock_acquired.wait(timeout=5)

    t_sync = threading.Thread(target=run_queued_sync)
    t_sync.start()

    # Restock Salt from 1 -> 10 while sync is waiting on _sync_lock
    with app.app_context():
        db.session.query(Item).filter_by(id=salt_id).update({"quantity": 10, "version": 2})
        db.session.commit()

    release_lock.set()
    t_holder.join(timeout=5)
    t_sync.join(timeout=5)

    assert len(results) == 1
    assert results[0]["synced_count"] == 0
    assert results[0]["status"] == "success"


def test_update_quantity_response_uses_committed_version_not_post_commit_select(app, client):
    from sqlalchemy import event

    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Mjölk", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

        def bump_after_commit(session):
            # Simulate another worker committing version=3, quantity=7 right after commit
            with db.engine.begin() as conn:
                conn.execute(
                    text("UPDATE item SET quantity = 7, version = 3 WHERE id = :id"),
                    {"id": item_id},
                )

        event.listen(db.session, "after_commit", bump_after_commit, once=True)

    res = client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "2", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["new_quantity"] == 2
    assert payload["version"] == 2


def test_backup_restore_after_delete_still_invalidates_deleted_item_version(app, client):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        item = Item(name="Te", quantity=1, alert_quantity=1, unit="st", unit_id=u.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    # Export at version=1
    backup_bytes = client.get("/settings/backup").get_data()

    # Bump to version=2 then delete
    res_bump = client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "4", "version": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_bump.status_code == 200
    assert res_bump.get_json()["version"] == 2

    res_del = client.post(
        f"/remove_item/{item_id}",
        data={"version": "2"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_del.status_code == 200

    # Restore backup -> version must be > 2 so old version=2 forms are rejected
    res_restore = client.post(
        "/settings/restore",
        data={"backup_file": (io.BytesIO(backup_bytes), "v1.json")},
        content_type="multipart/form-data",
    )
    assert res_restore.status_code == 302

    res_stale = client.post(
        "/update_quantity",
        data={"item_id": str(item_id), "new_quantity": "99", "version": "2"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_stale.status_code == 409

    with app.app_context():
        restored = db.session.get(Item, item_id)
        assert restored is not None
        assert restored.quantity == 1
        assert restored.version >= 3


def test_shopping_copy_button_handles_missing_clipboard_and_permission_error(app, client):
    html = client.get("/shopping").get_data(as_text=True)
    assert "copyToClipboard" in html
    assert "fallbackCopyText" in html
    assert "typeof navigator.clipboard.writeText === 'function'" in html
    assert ".catch(function()" in html
    assert "alert(T.common.error_generic)" in html


def test_ha_sync_omits_description_for_shopping_list_without_feature_64(app):
    with app.app_context():
        u = Unit(name="st")
        db.session.add(u)
        db.session.flush()
        db.session.add(Item(name="Bröd", quantity=0, alert_quantity=1, unit="st", unit_id=u.id))
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "tok")
        Settings.set("ha_default_todo_entity", "todo.shopping_list")
        db.session.commit()

        add_payloads: list[dict] = []

        class FakeResp:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

        def fake_get(url, headers=None, timeout=5):
            if url.endswith("/api/states/todo.shopping_list"):
                # HA built-in shopping_list: CREATE|DELETE|UPDATE|MOVE = 15 (no SET_DESCRIPTION_ON_ITEM=64)
                return FakeResp(
                    200,
                    {
                        "entity_id": "todo.shopping_list",
                        "attributes": {"supported_features": 15, "friendly_name": "Shopping List"},
                    },
                )
            raise AssertionError(f"Unexpected GET URL: {url}")

        def fake_post(url, headers=None, json=None, timeout=5):
            if "todo/get_items" in url:
                return FakeResp(200, {"service_response": {"todo.shopping_list": {"items": []}}})
            if "todo/add_item" in url:
                if "description" in (json or {}):
                    return FakeResp(400, {"message": "Entity does not support descriptions"})
                add_payloads.append(json)
                return FakeResp(200, {})
            raise AssertionError(f"Unexpected POST URL: {url}")

        with (
            patch("app.integrations.home_assistant.requests.get", fake_get),
            patch("app.integrations.home_assistant.requests.post", fake_post),
        ):
            res = sync_low_inventory_to_ha()
            assert res["status"] == "success"
            assert res["synced_count"] == 1
            assert len(add_payloads) == 1
            assert add_payloads[0] == {"entity_id": "todo.shopping_list", "item": "Bröd (0 st)"}
