"""Regression tests for security, Ingress, transactions, and HA To-do sync."""

from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.extensions import db
from app.models.item import Item
from app.models.settings import Settings
from app.services.shopping_sync import sync_low_inventory_to_ha


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


def test_wsgi_app_has_debug_disabled():
    import wsgi

    assert wsgi.app.debug is False


def test_test_ha_addon_mode_never_leaks_supervisor_token(client, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "super-secret-supervisor-token")
    called_urls = []

    def fake_get(url, headers=None, timeout=None):
        called_urls.append((url, headers))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = []
        return resp

    with patch("app.integrations.home_assistant.requests.get", side_effect=fake_get):
        res = client.post(
            "/settings/test_ha",
            data={"ha_url": "https://attacker.example.com", "ha_token": ""},
        )

    assert res.status_code == 200
    assert all(url.startswith("http://supervisor/core/") for url, _ in called_urls)
    assert not any("attacker.example.com" in url for url, _ in called_urls)


def test_standalone_url_change_requires_explicit_token(app, client, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with app.app_context():
        Settings.set("ha_url", "http://ha.local:8123")
        Settings.set("ha_token", "existing-secret-token")
        db.session.commit()

    with patch("app.integrations.home_assistant.requests.get") as mock_get:
        res_test = client.post(
            "/settings/test_ha",
            data={"ha_url": "https://attacker.example.com", "ha_token": ""},
        )
        res_save = client.post(
            "/settings/save",
            data={"ha_url": "https://attacker.example.com", "ha_token": ""},
        )

    assert res_test.status_code == 400
    assert res_test.get_json()["status"] == "error"
    assert res_save.status_code == 400
    mock_get.assert_not_called()


def test_save_settings_is_atomic_on_failure(app, client, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.initial")
        Settings.set("calendar_url", "https://initial.example.com")
        db.session.commit()

    res = client.post(
        "/settings/save",
        data={
            "ha_default_todo_entity": "todo.changed",
            "calendar_url": "https://changed.example.com",
            "opt_del_unit": "not-valid-json",
        },
    )
    assert res.status_code == 400

    with app.app_context():
        assert Settings.get("ha_default_todo_entity") == "todo.initial"
        assert Settings.get("calendar_url") == "https://initial.example.com"


def test_ingress_prefix_rewrites_static_links_and_redirects(client):
    res = client.get(
        "/",
        headers={"X-Ingress-Path": "/api/hassio_ingress/test-token"},
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "/api/hassio_ingress/test-token/static/style.css" in html
    assert "/api/hassio_ingress/test-token/update_quantity" in html

    redir = client.get(
        "/set_language/sv",
        headers={"X-Ingress-Path": "/api/hassio_ingress/test-token"},
    )
    assert redir.status_code == 302
    assert "/api/hassio_ingress/test-token/" in redir.headers["Location"]


def test_addon_mode_blocks_untrusted_direct_access(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    addon_app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with addon_app.app_context():
        db.create_all()
    addon_client = addon_app.test_client()

    blocked = addon_client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert blocked.status_code == 403

    allowed = addon_client.get(
        "/",
        environ_base={"REMOTE_ADDR": "172.30.32.2"},
        headers={"X-Ingress-Path": "/api/hassio_ingress/abc"},
    )
    assert allowed.status_code == 200


def test_ha_sync_exact_matching_does_not_skip_salt_for_ortsalt(app, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.add(
            Item(name="Salt", quantity=0, alert_quantity=1, unit="st", store="ICA", is_visible=True)
        )
        db.session.commit()

        added_payloads = []

        def fake_post(url, headers=None, json=None, timeout=None):
            resp = MagicMock()
            if "get_items" in url:
                resp.status_code = 200
                resp.json.return_value = {
                    "service_response": {
                        "todo.shopping": {
                            "items": [{"summary": "Örtsalt (1 st)", "status": "needs_action"}]
                        }
                    }
                }
            else:
                added_payloads.append(json)
                resp.status_code = 200
            return resp

        with patch("app.integrations.home_assistant.requests.post", side_effect=fake_post):
            result = sync_low_inventory_to_ha()

    assert result["status"] == "success"
    assert result["synced_count"] == 1
    assert result["skipped_count"] == 0
    assert added_payloads[0]["item"] == "Salt (0 st)"


def test_ha_sync_read_error_is_not_treated_as_empty_list(app, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.add(
            Item(name="Mjölk", quantity=0, alert_quantity=1, unit="l", store="ICA", is_visible=True)
        )
        db.session.commit()

        def fake_post(url, headers=None, json=None, timeout=None):
            if "add_item" in url:
                raise AssertionError("add_item must not be called when get_items fails")
            resp = MagicMock()
            resp.status_code = 500
            return resp

        with patch("app.integrations.home_assistant.requests.post", side_effect=fake_post):
            result = sync_low_inventory_to_ha()

    assert result["status"] == "error"
    assert result["synced_count"] == 0
    assert result["failed_count"] == 1


def test_ha_sync_reports_error_when_all_writes_fail(app, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    with app.app_context():
        Settings.set("ha_default_todo_entity", "todo.shopping")
        db.session.add(
            Item(name="Smör", quantity=0, alert_quantity=1, unit="st", store="ICA", is_visible=True)
        )
        db.session.commit()

        def fake_post(url, headers=None, json=None, timeout=None):
            resp = MagicMock()
            if "get_items" in url:
                resp.status_code = 200
                resp.json.return_value = {"service_response": {"todo.shopping": {"items": []}}}
            else:
                resp.status_code = 500
            return resp

        with patch("app.integrations.home_assistant.requests.post", side_effect=fake_post):
            result = sync_low_inventory_to_ha()

    assert result["status"] == "error"
    assert result["synced_count"] == 0
    assert result["failed_count"] == 1
