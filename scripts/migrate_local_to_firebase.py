"""Copy the local database (data/local_db.json) into Firebase Firestore.

Usage (from the project folder, with FIREBASE_SERVICE_ACCOUNT_BASE64 set in .env):

    python scripts/migrate_local_to_firebase.py            # show what would be copied
    python scripts/migrate_local_to_firebase.py --apply    # copy it

Every profile is copied. Accounts/categories with the same name as ones already in
Firestore are merged, and existing documents are never overwritten. After a successful
copy the local file is renamed to ``local_db.migrated-<date>.json`` so the same data is
not copied twice; the app then uses Firebase because the credential is set.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from firebase_store import firebase_client, firebase_credentials, firebase_project_id  # noqa: E402
from local_store import local_client, local_db_path, reset_local_client  # noqa: E402
from migration import migrate  # noqa: E402

LABELS = {"accounts": "akun", "categories": "kategori", "transactions": "transaksi",
          "budgets": "budget", "wishes": "wish", "settings": "preferensi",
          "integrations": "integrasi", "profiles": "profil"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Salin data lokal ke Firebase Firestore.")
    parser.add_argument("--apply", action="store_true", help="benar-benar menyalin (tanpa ini hanya menampilkan ringkasan)")
    args = parser.parse_args()

    if not firebase_credentials():
        print("FIREBASE_SERVICE_ACCOUNT_BASE64 belum diisi di file .env.")
        return 1
    source = local_db_path()
    if not source.exists():
        print(f"Tidak ada data lokal di {source}.")
        return 0
    local = local_client()
    counts = local.counts()
    print(f"Data lokal ({source.name}): " + ", ".join(f"{counts.get(k, 0)} {v}" for k, v in LABELS.items() if k in counts))
    print(f"Tujuan: project Firebase {firebase_project_id() or '(tidak diketahui)'}")
    if not args.apply:
        print("Jalankan lagi dengan --apply untuk menyalin.")
        return 0

    report = migrate(local, firebase_client())
    for name, item in report.items():
        print(f"  {LABELS.get(name, name)}: {item['copied']} disalin, {item['merged']} digabung, {item['skipped']} sudah ada")
    backup = source.with_name(f"local_db.migrated-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    source.rename(backup)
    reset_local_client()
    print(f"Selesai. File lokal disimpan sebagai cadangan: {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
