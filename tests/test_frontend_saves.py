"""Behavior checks for the actual rendered inventory JavaScript."""

import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app
from app.extensions import db


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for JavaScript checks")
def test_inventory_save_queue_and_dirty_state(tmp_path):
    with patch("app.config.get_or_create_secret_key", return_value="isolated-test-key"):
        app = create_app(
            {
                "TESTING": True,
                "ENFORCE_INGRESS_PROXY": False,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
    with app.app_context():
        db.create_all()
        try:
            html = app.test_client().get("/").get_data(as_text=True)
        finally:
            db.session.remove()
            db.engine.dispose()
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    source = next(script for script in scripts if "function saveItem" in script)
    script_file = tmp_path / "inventory.js"
    script_file.write_text(source)
    harness = Path(__file__).parent / "js" / "inventory_save.cjs"
    result = subprocess.run(
        [shutil.which("node"), str(harness), str(script_file)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
