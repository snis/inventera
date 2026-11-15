"""
Internationalization (i18n) helper using JSON translation files.
Supports automatic language detection (query param, cookie, env/config, Accept-Language)
and Home Assistant Add-on / Ingress language synchronization.
"""

import json
import os
from typing import Any

from flask import request, session

SUPPORTED_LANGUAGES = ["sv", "en"]
DEFAULT_LANGUAGE = os.environ.get("LANGUAGE", "sv").lower()[:2]
if DEFAULT_LANGUAGE not in SUPPORTED_LANGUAGES:
    DEFAULT_LANGUAGE = "en"

_TRANSLATIONS: dict[str, dict[str, Any]] = {}


def _load_translations() -> None:
    """Load all JSON translation files from app/translations/."""
    trans_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "translations")
    for lang in SUPPORTED_LANGUAGES:
        file_path = os.path.join(trans_dir, f"{lang}.json")
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as f:
                _TRANSLATIONS[lang] = json.load(f)


def get_locale() -> str:
    """Determine the best language for the current request."""
    if not _TRANSLATIONS:
        _load_translations()

    try:
        # 1. Explicit query parameter (?lang=en)
        query_lang = request.args.get("lang")
        if query_lang and query_lang[:2].lower() in SUPPORTED_LANGUAGES:
            lang = query_lang[:2].lower()
            session["lang"] = lang
            return lang

        # 2. Session or cookie preference
        session_lang = session.get("lang")
        if session_lang and session_lang in SUPPORTED_LANGUAGES:
            return session_lang

        cookie_lang = request.cookies.get("inventera_lang")
        if cookie_lang and cookie_lang[:2].lower() in SUPPORTED_LANGUAGES:
            return cookie_lang[:2].lower()

        # 3. Browser Accept-Language header
        best = request.accept_languages.best_match(SUPPORTED_LANGUAGES)
        if best:
            return best
    except RuntimeError:
        # Outside request context
        pass

    return DEFAULT_LANGUAGE


def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    """
    Translate a dot-notated key (e.g. 'nav.inventory').
    Falls back to English, then Swedish, then the key itself.
    """
    if not _TRANSLATIONS:
        _load_translations()

    active_lang = lang or get_locale()
    parts = key.split(".")

    def _lookup(language: str) -> Any:
        data = _TRANSLATIONS.get(language, {})
        for part in parts:
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return None
        return data

    val = _lookup(active_lang)
    if val is None and active_lang != "en":
        val = _lookup("en")
    if val is None and active_lang != "sv":
        val = _lookup("sv")
    if val is None:
        return key

    if isinstance(val, str) and kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return str(val)


def get_translations_dict(lang: str | None = None) -> dict[str, Any]:
    """Return full translation dictionary for the given language (for JS usage)."""
    if not _TRANSLATIONS:
        _load_translations()
    active_lang = lang or get_locale()
    return _TRANSLATIONS.get(active_lang, _TRANSLATIONS.get("en", {}))
