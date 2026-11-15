"""Data store selection and small record helpers.

* Firebase mode: Firestore via the Admin SDK, when ``FIREBASE_SERVICE_ACCOUNT_BASE64``
  is set in the environment.
* Local mode: a JSON file in ``data/`` (see local_store.py) when it is not.
  Existing local data can be copied to Firebase later with
  ``python scripts/migrate_local_to_firebase.py``.

Firebase Admin credentials stay server-side; they are never sent to the browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache

from config_store import cfg
from local_store import local_client

def decode_service_account(encoded: str) -> dict:
    try:
        account = json.loads(base64.b64decode(encoded, validate=True))
    except Exception as exc:
        raise RuntimeError("Kredensial Firebase Base64 tidak valid") from exc
    if not isinstance(account, dict) or account.get("type") != "service_account" or not account.get("project_id"):
        raise RuntimeError("Kredensial Firebase bukan service account yang valid")
    return account


@lru_cache(maxsize=4)
def _firebase_services(encoded: str, bucket_name: str):
    account = decode_service_account(encoded)
    import firebase_admin
    from firebase_admin import credentials, firestore

    # One named app per credential, so changing credentials at runtime starts a fresh app.
    name = "mfd-" + hashlib.sha256(encoded.encode()).hexdigest()[:12]
    try:
        firebase_app = firebase_admin.get_app(name)
    except ValueError:
        options = {"storageBucket": bucket_name} if bucket_name else None
        firebase_app = firebase_admin.initialize_app(credentials.Certificate(account), options, name=name)
    bucket = None
    if bucket_name:
        from firebase_admin import storage
        bucket = storage.bucket(app=firebase_app)
    return firestore.client(app=firebase_app), bucket


def firebase_credentials() -> str:
    return cfg("FIREBASE_SERVICE_ACCOUNT_BASE64")


def firebase_project_id() -> str | None:
    encoded = firebase_credentials()
    if not encoded:
        return None
    try:
        return decode_service_account(encoded).get("project_id")
    except RuntimeError:
        return None


def firebase_services():
    encoded = firebase_credentials()
    if not encoded:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_BASE64 belum diatur")
    return _firebase_services(encoded, cfg("FIREBASE_STORAGE_BUCKET"))


def firebase_client():
    """The Firestore client, regardless of which store is active (used by migration)."""
    return firebase_services()[0]


def storage_mode() -> str:
    """'firebase' when Firebase credentials are configured, otherwise 'local'."""
    return "firebase" if firebase_credentials() else "local"


DEFAULT_PROFILE = "default"
# Collections that belong to one profile. Everything else (profiles list, Drive integration)
# is shared by the whole login.
PROFILE_COLLECTIONS = frozenset({"accounts", "categories", "transactions", "budgets", "wishes", "settings"})
_profile_resolver = lambda: DEFAULT_PROFILE  # noqa: E731  (app.py points this at the session)


def set_profile_resolver(resolver) -> None:
    global _profile_resolver
    _profile_resolver = resolver


class ProfileScopedClient:
    """Routes per-profile collections to ``profiles/{id}/{collection}``.

    The default profile keeps using the top-level collections, so data created before
    profiles existed stays exactly where it was.
    """

    def __init__(self, raw, profile_id: str):
        self.raw, self.profile_id = raw, profile_id

    def collection(self, name: str):
        if name in PROFILE_COLLECTIONS:
            return self.raw.collection("profiles").document(self.profile_id).collection(name)
        return self.raw.collection(name)

    def batch(self):
        return self.raw.batch()


def scoped(raw, profile_id: str):
    return raw if not profile_id or profile_id == DEFAULT_PROFILE else ProfileScopedClient(raw, profile_id)


def raw_client():
    """Active store without profile scoping."""
    return firebase_client() if storage_mode() == "firebase" else local_client()


def firestore_client():
    """Active data store for the active profile: Firestore in Firebase mode, otherwise local."""
    return scoped(raw_client(), _profile_resolver())


def storage_bucket():
    if storage_mode() != "firebase":
        raise RuntimeError("Foto struk lama di Firebase Storage hanya tersedia dalam mode Firebase")
    bucket = firebase_services()[1]
    if bucket is None:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET belum diatur; fitur foto struk memerlukan Firebase Storage")
    return bucket


def list_records(collection: str, client=None) -> list[dict]:
    """``client`` lets worker threads (which have no Flask request, so no session and no
    active profile) read with the store the request thread already resolved."""
    client = client or firestore_client()
    return [doc.to_dict() | {"id": doc.id} for doc in client.collection(collection).stream()]


def get_record(collection: str, record_id: str) -> dict | None:
    snapshot = firestore_client().collection(collection).document(str(record_id)).get()
    return snapshot.to_dict() | {"id": snapshot.id} if snapshot.exists else None


def put_record(collection: str, record_id: str, data: dict) -> None:
    firestore_client().collection(collection).document(str(record_id)).set(data)


def create_record(collection: str, data: dict, record_id: str | None = None) -> str:
    client = firestore_client()
    ref = client.collection(collection).document(record_id) if record_id else client.collection(collection).document()
    ref.set(data)
    return ref.id


def delete_record(collection: str, record_id: str) -> None:
    firestore_client().collection(collection).document(str(record_id)).delete()
