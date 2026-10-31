"""Lazy Firebase Admin clients and small Firestore/Storage helpers.

Only server-side code uses this module. Firebase Admin credentials must never be
placed in browser assets or committed to the repository.
"""
from __future__ import annotations

import base64
import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def firebase_services():
    encoded = os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64", "").strip()
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if not encoded:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_BASE64 belum diatur")
    try:
        service_account = json.loads(base64.b64decode(encoded, validate=True))
    except Exception as exc:
        raise RuntimeError("Kredensial Firebase Base64 tidak valid") from exc

    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        firebase_app = firebase_admin.get_app()
    except ValueError:
        options = {"storageBucket": bucket_name} if bucket_name else None
        firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(service_account),
            options,
        )
    if bucket_name:
        from firebase_admin import storage
        bucket = storage.bucket(app=firebase_app)
    else:
        bucket = None
    return firestore.client(app=firebase_app), bucket


def firestore_client():
    return firebase_services()[0]


def storage_bucket():
    bucket = firebase_services()[1]
    if bucket is None:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET belum diatur; fitur foto struk memerlukan Firebase Storage")
    return bucket


def list_records(collection: str) -> list[dict]:
    return [doc.to_dict() | {"id": doc.id} for doc in firestore_client().collection(collection).stream()]


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

