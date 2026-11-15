"""Copy data from the local store into Firestore (or any store with the same client API).

Rules, chosen so a migration never duplicates or overwrites data:
* Document IDs are kept. A document whose ID already exists in the target is skipped.
* Accounts with the same name (spacing/case-insensitive) and categories with the same
  name + kind are merged into the existing target record instead of being duplicated;
  every reference (transactions, budgets, wishes) is rewritten to the target ID.
* A budget for a category that already has an active budget in the target is skipped.
* Running it twice is safe: everything already copied is skipped the second time.
* Every profile is migrated: the default profile's top-level collections, the
  ``profiles`` list itself, and each extra profile's ``profiles/{id}/...`` collections.
"""
from __future__ import annotations

import unicodedata

from firebase_store import DEFAULT_PROFILE, scoped

COLLECTIONS = ("accounts", "categories", "transactions", "budgets", "wishes", "settings", "integrations")
PROFILE_DATA = ("accounts", "categories", "transactions", "budgets", "wishes", "settings")
BATCH_LIMIT = 400  # Firestore allows 500 writes per batch


def normalize_name(value) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def snapshot(client, names=COLLECTIONS) -> dict:
    return {name: {doc.id: doc.to_dict() for doc in client.collection(name).stream()} for name in names}


def plan_migration(source: dict, target: dict) -> tuple[list, dict]:
    """Return (writes, report). writes = [(collection, doc_id, data, merge)]."""
    source = {name: source.get(name, {}) for name in COLLECTIONS}
    target = {name: target.get(name, {}) for name in COLLECTIONS}
    report = {name: {"copied": 0, "merged": 0, "skipped": 0} for name in COLLECTIONS}
    writes = []

    def copy(name, doc_id, data):
        writes.append((name, doc_id, data, False))
        report[name]["copied"] += 1

    # Accounts: merge by name.
    account_map = {}
    target_accounts = {normalize_name(d.get("name")): doc_id for doc_id, d in target["accounts"].items() if d.get("active", True)}
    for doc_id, data in source["accounts"].items():
        if doc_id in target["accounts"]:
            account_map[doc_id] = doc_id
            report["accounts"]["skipped"] += 1
        elif normalize_name(data.get("name")) in target_accounts and data.get("active", True):
            existing_id = target_accounts[normalize_name(data.get("name"))]
            account_map[doc_id] = existing_id
            report["accounts"]["merged"] += 1
            # A freshly created Firebase project only has 0-balance default accounts:
            # keep the local opening balance in that case.
            local_initial = int(data.get("initial_cents") or 0)
            if local_initial and not int(target["accounts"][existing_id].get("initial_cents") or 0):
                writes.append(("accounts", existing_id, {"initial_cents": local_initial, "created_at": data.get("created_at")}, True))
        else:
            account_map[doc_id] = doc_id
            copy("accounts", doc_id, data)

    # Categories: merge by name + kind.
    category_map = {}
    target_categories = {(normalize_name(d.get("name")), d.get("kind")): doc_id for doc_id, d in target["categories"].items() if d.get("active", True)}
    for doc_id, data in source["categories"].items():
        key = (normalize_name(data.get("name")), data.get("kind"))
        if doc_id in target["categories"]:
            category_map[doc_id] = doc_id
            report["categories"]["skipped"] += 1
        elif key in target_categories and data.get("active", True):
            category_map[doc_id] = target_categories[key]
            report["categories"]["merged"] += 1
        else:
            category_map[doc_id] = doc_id
            copy("categories", doc_id, data)

    def remap(value, mapping):
        return mapping.get(str(value), value) if value else value

    for doc_id, data in source["transactions"].items():
        if doc_id in target["transactions"]:
            report["transactions"]["skipped"] += 1
            continue
        copy("transactions", doc_id, data | {
            "account_id": remap(data.get("account_id"), account_map),
            "destination_id": remap(data.get("destination_id"), account_map),
            "category_id": remap(data.get("category_id"), category_map),
        })

    budgeted = {str(d.get("category_id")) for d in target["budgets"].values() if d.get("active", True)}
    for doc_id, data in source["budgets"].items():
        category_id = remap(data.get("category_id"), category_map)
        if doc_id in target["budgets"] or (data.get("active", True) and str(category_id) in budgeted):
            report["budgets"]["skipped"] += 1
            continue
        budgeted.add(str(category_id))
        copy("budgets", doc_id, data | {"category_id": category_id})

    linked = {str(d.get("linked_account_id")) for d in target["wishes"].values() if d.get("linked_account_id")}
    for doc_id, data in source["wishes"].items():
        if doc_id in target["wishes"]:
            report["wishes"]["skipped"] += 1
            continue
        account_id = remap(data.get("linked_account_id"), account_map)
        if account_id and str(account_id) in linked:
            account_id = None  # one pocket funds one wish; fall back to manual allocation
        if account_id:
            linked.add(str(account_id))
        copy("wishes", doc_id, data | {"linked_account_id": account_id})

    for name in ("settings", "integrations"):
        for doc_id, data in source[name].items():
            if doc_id in target[name]:
                report[name]["skipped"] += 1
            else:
                copy(name, doc_id, data)
    return writes, report


def migrate(source_client, target_client) -> dict:
    """Migrate every profile. Returns per-collection totals summed over all profiles."""
    jobs = []  # (target scope, writes)
    writes, report = plan_migration(snapshot(source_client), snapshot(target_client))
    jobs.append((target_client, writes))

    # The profiles list (shared), then each extra profile's own collections.
    source_profiles = {doc.id: doc.to_dict() for doc in source_client.collection("profiles").stream()}
    target_profiles = {doc.id for doc in target_client.collection("profiles").stream()}
    profile_writes = [("profiles", pid, data, False) for pid, data in source_profiles.items() if pid not in target_profiles]
    jobs.append((target_client, profile_writes))
    report["profiles"] = {"copied": len(profile_writes), "merged": 0, "skipped": len(source_profiles) - len(profile_writes)}
    for pid in source_profiles:
        if pid == DEFAULT_PROFILE:
            continue
        source_scope, target_scope = scoped(source_client, pid), scoped(target_client, pid)
        writes, part = plan_migration(snapshot(source_scope, PROFILE_DATA), snapshot(target_scope, PROFILE_DATA))
        jobs.append((target_scope, writes))
        for name, counts in part.items():
            for key, value in counts.items():
                report[name][key] += value

    for scope, writes in jobs:
        for start in range(0, len(writes), BATCH_LIMIT):
            batch = target_client.batch()
            for name, doc_id, data, merge in writes[start:start + BATCH_LIMIT]:
                batch.set(scope.collection(name).document(doc_id), data, merge=merge)
            batch.commit()
    return report
