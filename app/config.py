"""Application configuration, paths, runtime mode, and UTC time helper."""

import os
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_INGRESS_PROXY = "172.30.32.2"


def utc_now() -> datetime:
    """Return current UTC time as naive datetime for consistent SQLite storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def is_addon_mode() -> bool:
    """Return True when running inside a Home Assistant Supervisor add-on."""
    return bool(os.environ.get("SUPERVISOR_TOKEN", "").strip())


def resolve_data_dir(app_root: Path) -> Path:
    """Return persistent data directory (/data in add-on mode, instance/ otherwise)."""
    if is_addon_mode() and Path("/data").is_dir():
        return Path("/data")
    return app_root.parent / "instance"


def get_or_create_secret_key(data_dir: Path) -> str:
    """Load SECRET_KEY from env, or persist a generated key inside data_dir."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key

    key_file = data_dir / ".secret_key"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        if key_file.is_file():
            stored = key_file.read_text(encoding="utf-8").strip()
            if stored:
                return stored
        generated = os.urandom(32).hex()
        key_file.write_text(generated, encoding="utf-8")
        return generated
    except OSError:
        return os.urandom(32).hex()


def build_config(app_root: Path, test_config: dict | None = None) -> dict:
    """Build Flask configuration dictionary for standalone, add-on, or test mode."""
    data_dir = resolve_data_dir(app_root)
    db_file = data_dir / "db.sqlite3"
    addon = is_addon_mode()

    config: dict = {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "JSON_SORT_KEYS": False,
        "SECRET_KEY": get_or_create_secret_key(data_dir),
        "ENFORCE_INGRESS_PROXY": addon,
    }
    if test_config:
        config.update(test_config)
    return config
