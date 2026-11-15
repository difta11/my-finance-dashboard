"""Configuration (environment only) and a small app-state file.

Configuration for AI, Google Drive and Firebase comes only from environment variables
(``.env`` locally, Environment Variables on Vercel). The state file in ``data/`` only keeps
app state such as the last used profile; it never holds secrets.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_lock = threading.RLock()


def is_vercel() -> bool:
    return os.getenv("VERCEL", "").lower() == "1"


def cfg(name: str, default: str = "") -> str:
    """Environment variable, stripped, or ``default`` when unset/empty."""
    return os.getenv(name, "").strip() or default


def data_dir() -> Path:
    """Folder for the local database and app state (``APP_DATA_DIR`` overrides it)."""
    custom = os.getenv("APP_DATA_DIR", "").strip()
    if custom:
        path = Path(custom)
    elif is_vercel():
        path = Path(tempfile.gettempdir()) / "my-finance-data"
    else:
        path = ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_atomic(path: Path, payload) -> None:
    """Write via a temp file + rename so a crash never leaves half a JSON file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def state_path() -> Path:
    return data_dir() / "state.json"


def load_state() -> dict:
    with _lock:
        path = state_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


def save_state(section: str, updates: dict) -> dict:
    """Merge ``updates`` into one section; a value of None deletes that key."""
    with _lock:
        data = load_state()
        current = dict(data.get(section) or {})
        for key, value in updates.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        data[section] = current
        write_json_atomic(state_path(), data)
        return current
