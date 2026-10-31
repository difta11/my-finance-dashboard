"""One-time, non-destructive migration from the previous SQLite schema."""
from __future__ import annotations

import argparse
import mimetypes
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from firebase_store import firestore_client, list_records, storage_bucket


COLLECTIONS = ("accounts", "categories", "transactions", "wishes")


def read_legacy_database(database_path: Path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        result = {}
        for table in COLLECTIONS:
            result[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        return result
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Copy the old SQLite ledger into a Firebase project.")
    parser.add_argument("database", type=Path, help="Path to the old finance.db or .sqlite file")
    parser.add_argument("--receipts-dir", type=Path, help="Folder containing old receipt image files")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("SQLite database file was not found")

    try:
        legacy = read_legacy_database(args.database)
    except sqlite3.Error:
        parser.error("The SQLite database does not have the expected finance tables")
    for collection in COLLECTIONS:
        if list_records(collection):
            parser.error(f"Firestore collection '{collection}' is not empty; refusing to mix data")

    receipt_paths = {}
    for tx in legacy["transactions"]:
        filename = tx.get("receipt_file")
        if filename:
            source = (args.receipts_dir or args.database.parent / "receipts") / filename
            if not source.is_file():
                parser.error(f"A receipt referenced by the database is missing from the receipts folder")
            receipt_paths[filename] = source

    client = firestore_client()
    bucket = storage_bucket() if receipt_paths else None
    for collection in ("accounts", "categories", "wishes", "transactions"):
        rows = legacy[collection]
        for offset in range(0, len(rows), 450):
            batch = client.batch()
            for row in rows[offset:offset + 450]:
                old_id = str(row.pop("id"))
                if collection == "transactions":
                    row["category_id"] = str(row["category_id"]) if row.get("category_id") is not None else None
                    row["account_id"] = str(row["account_id"]) if row.get("account_id") is not None else None
                    row["destination_id"] = str(row["destination_id"]) if row.get("destination_id") is not None else None
                doc = client.collection(collection).document(old_id)
                batch.set(doc, row)
            batch.commit()

    for filename, source in receipt_paths.items():
        destination = bucket.blob("receipts/" + filename)
        destination.upload_from_filename(source, content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")

    print(f"Migrated {sum(len(legacy[name]) for name in COLLECTIONS)} documents and {len(receipt_paths)} receipt images.")
    print("The SQLite database and receipt files were left unchanged. Verify the deployed dashboard before archiving the source copy.")


if __name__ == "__main__":
    main()
