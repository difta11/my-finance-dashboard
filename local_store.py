"""Local storage used when no Firebase credentials are configured.

It mimics the small part of the Firestore client API that the app uses
(collection().document().get/set/update/create/delete, collection().stream(), batch()),
so the rest of the code works the same in both modes. Data is one JSON file in ``data/``,
so it is only available on the machine that runs the app.
"""
from __future__ import annotations

import json
import secrets
import string
import threading
from pathlib import Path

from google.api_core.exceptions import Conflict, NotFound

from config_store import data_dir, write_json_atomic

ID_ALPHABET = string.ascii_letters + string.digits
DATA_COLLECTIONS = ("accounts", "categories", "transactions", "budgets", "wishes", "debts")


def new_id() -> str:
    """20 random letters/digits, like Firestore auto IDs."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(20))


def resolve_value(old, value):
    """Apply Firestore field transforms we use (Increment) to a plain value."""
    if type(value).__name__ == "Increment":
        return (old or 0) + value.value
    return value


class LocalSnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self._data)) if self._data is not None else None


class LocalDocument:
    def __init__(self, client: "LocalClient", collection: str, doc_id: str | None = None):
        self._client, self._collection = client, collection
        self.id = doc_id or new_id()

    def get(self) -> LocalSnapshot:
        with self._client.lock:
            return LocalSnapshot(self.id, self._client.data.get(self._collection, {}).get(self.id))

    def set(self, data: dict, merge: bool = False) -> None:
        with self._client.lock:
            docs = self._client.data.setdefault(self._collection, {})
            current = dict(docs.get(self.id) or {}) if merge else {}
            for key, value in data.items():
                current[key] = resolve_value(current.get(key), value)
            docs[self.id] = current
            self._client.save()

    def create(self, data: dict) -> None:
        with self._client.lock:
            if self.id in self._client.data.get(self._collection, {}):
                raise Conflict(f"Document {self._collection}/{self.id} already exists")
            self.set(data)

    def update(self, data: dict) -> None:
        with self._client.lock:
            docs = self._client.data.get(self._collection, {})
            if self.id not in docs:
                raise NotFound(f"Document {self._collection}/{self.id} not found")
            self.set(data, merge=True)

    def delete(self) -> None:
        with self._client.lock:
            self._client.data.get(self._collection, {}).pop(self.id, None)
            self._client.save()

    def collection(self, name: str) -> "LocalCollection":
        """Subcollection, stored under the key ``{collection}/{doc_id}/{name}``."""
        return LocalCollection(self._client, f"{self._collection}/{self.id}/{name}")


class LocalCollection:
    def __init__(self, client: "LocalClient", name: str):
        self._client, self.name = client, name

    def document(self, doc_id: str | None = None) -> LocalDocument:
        return LocalDocument(self._client, self.name, str(doc_id) if doc_id else None)

    def stream(self):
        with self._client.lock:
            docs = self._client.data.get(self.name, {})
            return [LocalSnapshot(doc_id, data) for doc_id, data in docs.items()]


class LocalBatch:
    """Applies queued writes together and saves the file once."""

    def __init__(self, client: "LocalClient"):
        self._client, self._ops = client, []

    def set(self, ref: LocalDocument, data: dict, merge: bool = False):
        self._ops.append(("set", ref, data, merge))

    def update(self, ref: LocalDocument, data: dict):
        self._ops.append(("update", ref, data, False))

    def delete(self, ref: LocalDocument):
        self._ops.append(("delete", ref, None, False))

    def commit(self):
        with self._client.lock:
            self._client.autosave = False
            try:
                for op, ref, data, merge in self._ops:
                    if op == "set":
                        ref.set(data, merge=merge)
                    elif op == "update":
                        ref.update(data)
                    else:
                        ref.delete()
            finally:
                self._client.autosave = True
                self._client.save()


class LocalClient:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = threading.RLock()
        self.autosave = True
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self._data = {}
            if self.path and self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    self._data = loaded if isinstance(loaded, dict) else {}
                except (OSError, ValueError):
                    self._data = {}
        return self._data

    def save(self) -> None:
        if self.path and self.autosave:
            write_json_atomic(self.path, self.data)

    def collection(self, name: str) -> LocalCollection:
        return LocalCollection(self, name)

    def batch(self) -> LocalBatch:
        return LocalBatch(self)

    def _keys_for(self, name: str) -> list[str]:
        """Top-level key plus every profile's ``profiles/{id}/{name}`` key."""
        return [key for key in self.data if key == name or key.endswith("/" + name)]

    def counts(self) -> dict:
        """Totals across all profiles."""
        with self.lock:
            return {name: sum(len(self.data[key]) for key in self._keys_for(name)) for name in DATA_COLLECTIONS}

    def has_user_data(self) -> bool:
        """True when anything beyond the auto-created default accounts/categories exists."""
        counts = self.counts()
        return (any(counts[name] for name in ("transactions", "budgets", "wishes", "debts"))
                or self._non_default_entities()
                or any(pid != "default" for pid in self.data.get("profiles", {})))

    def _non_default_entities(self) -> bool:
        # Default accounts start at 0 balance; any non-zero initial balance means user data.
        return any(int((doc or {}).get("initial_cents") or 0)
                   for key in self._keys_for("accounts") for doc in self.data[key].values())


_client: LocalClient | None = None
_client_lock = threading.Lock()


def local_db_path() -> Path:
    return data_dir() / "local_db.json"


def local_client() -> LocalClient:
    global _client
    with _client_lock:
        if _client is None or _client.path != local_db_path():
            _client = LocalClient(local_db_path())
        return _client


def reset_local_client() -> None:
    global _client
    with _client_lock:
        _client = None
