"""Local store, env config, app state, profiles and local-to-Firebase migration (no network, no Firebase)."""
import json

import pytest
from google.api_core.exceptions import Conflict, NotFound
from google.cloud.firestore import Increment

import config_store
from local_store import LocalClient
from migration import migrate


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    for name in ("GEMINI_API_KEY", "AI_PROVIDER", "FIREBASE_SERVICE_ACCOUNT_BASE64"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_local_client_persists_and_mimics_firestore(tmp_path):
    path = tmp_path / "db.json"
    client = LocalClient(path)
    ref = client.collection("wishes").document("w1")
    ref.create({"name": "Kamera", "manual_saved_cents": 100})
    with pytest.raises(Conflict):
        ref.create({"name": "dupe"})
    ref.update({"manual_saved_cents": Increment(50)})
    with pytest.raises(NotFound):
        client.collection("wishes").document("missing").update({"x": 1})
    batch = client.batch()
    batch.set(client.collection("accounts").document("a1"), {"name": "Cash"})
    batch.set(client.collection("accounts").document("a1"), {"initial_cents": 5}, merge=True)
    batch.commit()
    reloaded = LocalClient(path)
    assert reloaded.collection("wishes").document("w1").get().to_dict()["manual_saved_cents"] == 150
    assert reloaded.collection("accounts").document("a1").get().to_dict() == {"name": "Cash", "initial_cents": 5}
    assert len(client.collection("accounts").document().id) == 20
    assert json.loads(path.read_text(encoding="utf-8"))["accounts"]["a1"]["name"] == "Cash"


def test_has_user_data_ignores_untouched_defaults(tmp_path):
    client = LocalClient(tmp_path / "db.json")
    client.collection("accounts").document("a").set({"name": "Cash", "initial_cents": 0})
    assert client.has_user_data() is False
    client.collection("transactions").document("t").set({"kind": "expense"})
    assert client.has_user_data() is True


def test_cfg_reads_only_the_environment(data_dir, monkeypatch):
    assert config_store.cfg("GEMINI_API_KEY", "none") == "none"
    monkeypatch.setenv("GEMINI_API_KEY", "  from-env  ")
    assert config_store.cfg("GEMINI_API_KEY") == "from-env"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert config_store.cfg("GEMINI_API_KEY", "none") == "none"


def test_state_file_merges_and_deletes_keys(data_dir):
    assert config_store.load_state() == {}
    config_store.save_state("profiles", {"last_used": "p1", "extra": 1})
    config_store.save_state("profiles", {"extra": None})
    assert config_store.load_state() == {"profiles": {"last_used": "p1"}}
    assert (data_dir / "state.json").exists()
    (data_dir / "state.json").write_text("not json", encoding="utf-8")
    assert config_store.load_state() == {}


def seed(client, collection, doc_id, data):
    client.collection(collection).document(doc_id).set(data)


def test_migration_merges_same_names_and_rewrites_references(tmp_path):
    local, remote = LocalClient(tmp_path / "local.json"), LocalClient(tmp_path / "remote.json")
    # Remote = fresh Firebase project with auto-created defaults (different IDs, 0 balance).
    seed(remote, "accounts", "R-cash", {"name": "Cash", "initial_cents": 0, "active": True})
    seed(remote, "categories", "R-food", {"name": "Makanan & Minuman", "kind": "expense", "active": True})
    seed(remote, "budgets", "R-b", {"category_id": "R-food", "active": True, "name": "Remote food"})
    # Local data.
    seed(local, "accounts", "L-cash", {"name": " cash ", "initial_cents": 500, "active": True})
    seed(local, "accounts", "L-bca", {"name": "BCA", "initial_cents": 900, "active": True})
    seed(local, "categories", "L-food", {"name": "makanan & minuman", "kind": "expense", "active": True})
    seed(local, "categories", "L-pet", {"name": "Kucing", "kind": "expense", "active": True})
    seed(local, "transactions", "t1", {"kind": "expense", "account_id": "L-cash", "category_id": "L-food", "amount_cents": 10})
    seed(local, "transactions", "t2", {"kind": "transfer", "account_id": "L-bca", "destination_id": "L-cash", "category_id": None, "amount_cents": 5})
    seed(local, "budgets", "L-b1", {"category_id": "L-food", "active": True, "name": "Local food"})
    seed(local, "budgets", "L-b2", {"category_id": "L-pet", "active": True, "name": "Kucing"})
    seed(local, "wishes", "w1", {"name": "Liburan", "linked_account_id": "L-bca"})

    report = migrate(local, remote)

    accounts = {s.id: s.to_dict() for s in remote.collection("accounts").stream()}
    assert set(accounts) == {"R-cash", "L-bca"}  # "cash" merged into the remote Cash
    assert accounts["R-cash"]["initial_cents"] == 500  # local opening balance kept
    t1 = remote.collection("transactions").document("t1").get().to_dict()
    assert t1["account_id"] == "R-cash" and t1["category_id"] == "R-food"
    t2 = remote.collection("transactions").document("t2").get().to_dict()
    assert t2["account_id"] == "L-bca" and t2["destination_id"] == "R-cash"
    budgets = {s.id for s in remote.collection("budgets").stream()}
    assert budgets == {"R-b", "L-b2"}  # food already budgeted remotely
    assert remote.collection("wishes").document("w1").get().to_dict()["linked_account_id"] == "L-bca"
    assert report["accounts"] == {"copied": 1, "merged": 1, "skipped": 0}
    assert report["budgets"] == {"copied": 1, "merged": 0, "skipped": 1}

    # Running it again copies nothing new.
    again = migrate(local, remote)
    assert again["transactions"] == {"copied": 0, "merged": 0, "skipped": 2}
    assert len(list(remote.collection("transactions").stream())) == 2


def test_profiles_keep_separate_data_and_migrate(tmp_path):
    from firebase_store import scoped

    local, remote = LocalClient(tmp_path / "local.json"), LocalClient(tmp_path / "remote.json")
    default, work = scoped(local, "default"), scoped(local, "work")
    default.collection("transactions").document("t-home").set({"kind": "expense", "amount_cents": 1})
    work.collection("transactions").document("t-work").set({"kind": "expense", "amount_cents": 2})
    local.collection("profiles").document("work").set({"name": "Usaha"})
    # Same collection name, different data per profile; the profiles list is shared.
    assert [d.id for d in default.collection("transactions").stream()] == ["t-home"]
    assert [d.id for d in work.collection("transactions").stream()] == ["t-work"]
    assert [d.id for d in work.collection("profiles").stream()] == ["work"]
    assert local.counts()["transactions"] == 2 and local.has_user_data()

    report = migrate(local, remote)
    assert [d.id for d in scoped(remote, "work").collection("transactions").stream()] == ["t-work"]
    assert [d.id for d in remote.collection("transactions").stream()] == ["t-home"]
    assert remote.collection("profiles").document("work").get().to_dict()["name"] == "Usaha"
    assert report["transactions"]["copied"] == 2 and report["profiles"]["copied"] == 1


@pytest.fixture
def client(data_dir, monkeypatch):
    """Flask test client on an empty local store, logged in."""
    import app as app_module
    import local_store

    for name in ("FIREBASE_SERVICE_ACCOUNT_BASE64", "GEMINI_API_KEY", "OPENAI_API_KEY", "GOOGLE_DRIVE_CLIENT_ID"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-pass")
    local_store.reset_local_client()
    web = app_module.app.test_client()
    csrf = web.post("/api/login", json={"password": "test-pass"}).get_json()["csrf"]
    web.environ_base["HTTP_X_CSRF_TOKEN"] = csrf
    yield web
    local_store.reset_local_client()


def test_profile_has_no_email_and_can_be_deleted_with_its_data(client, data_dir):
    import local_store

    created = client.post("/api/profiles", json={"name": "Usaha", "email": "x@y.z"}).get_json()
    usaha = next(p for p in created["profiles"] if p["name"] == "Usaha")
    assert created["active"] == usaha["id"] and "email" not in usaha
    boot = client.get("/api/bootstrap").get_json()  # creates the default accounts/categories
    cash = next(a for a in boot["accounts"] if a["name"] == "Cash")
    food = next(c for c in boot["categories"] if c["kind"] == "expense")
    saved = client.post("/api/transactions", json={"kind": "expense", "amount": "5000", "account_id": cash["id"], "category_id": food["id"]})
    assert saved.status_code in (200, 201), saved.get_json()
    counts = client.get(f"/api/profiles/{usaha['id']}/summary").get_json()["counts"]
    assert counts["transactions"] == 1 and counts["accounts"] >= 1

    assert client.delete("/api/profiles/default").status_code == 400
    after = client.delete(f"/api/profiles/{usaha['id']}").get_json()
    assert after["active"] == "default" and [p["id"] for p in after["profiles"]] == ["default"]
    leftovers = [key for key, docs in local_store.local_client().data.items() if usaha["id"] in key and docs]
    assert leftovers == []
    assert client.delete(f"/api/profiles/{usaha['id']}").status_code == 404
    assert config_store.load_state()["profiles"]["last_used"] == "default"


def test_settings_endpoints_are_gone(client):
    assert client.get("/api/settings").status_code == 404
    assert client.post("/api/settings/migration", json={"action": "migrate"}).status_code in (404, 405)
