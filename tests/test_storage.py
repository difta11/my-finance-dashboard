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


def boot_data(client):
    return client.get("/api/bootstrap").get_json()


def balance_of(boot, name):
    return next(a["balance_cents"] for a in boot["accounts"] if a["name"] == name)


def test_my_debt_paid_from_an_account_becomes_an_expense(client):
    boot = boot_data(client)
    assert boot["debts"] == []
    cash = next(a for a in boot["accounts"] if a["name"] == "Cash")
    food = next(c for c in boot["categories"] if c["kind"] == "expense")
    expense_before, cash_before = boot["summary"]["expense_cents"], cash["balance_cents"]

    base = {"direction": "mine", "name": " Budi ", "amount": "50000", "category_id": food["id"], "note": "makan"}
    assert client.post("/api/debts", json=base | {"category_id": ""}).status_code == 400
    assert client.post("/api/debts", json=base | {"direction": "loan"}).status_code == 400
    assert client.post("/api/debts", json=base | {"debt_on": "2999-01-01"}).status_code == 400
    debt_id = client.post("/api/debts", json=base).get_json()["id"]
    boot = boot_data(client)
    assert balance_of(boot, "Cash") == cash_before  # recording what I owe moves no money
    debt = boot["debts"][0]
    assert debt["name"] == "Budi" and debt["settled"] is False and debt["category"] == food["name"]
    assert client.put(f"/api/debts/{debt_id}", json=base | {"amount": "60000"}).status_code == 200
    assert client.delete(f"/api/categories/{food['id']}").status_code == 409  # still needed by the debt

    # Ticking needs the paying account and records an expense in the debt's category.
    assert client.post(f"/api/debts/{debt_id}/settle", json={}).status_code == 400
    assert client.post(f"/api/debts/{debt_id}/settle", json={"account_id": cash["id"]}).status_code == 200
    assert client.post(f"/api/debts/{debt_id}/settle", json={"account_id": cash["id"]}).status_code == 409
    assert client.put(f"/api/debts/{debt_id}", json=base).status_code == 409
    boot = boot_data(client)
    debt = boot["debts"][0]
    assert debt["settled"] and debt["account"] == "Cash" and debt["transaction_id"]
    assert balance_of(boot, "Cash") == cash_before - 6_000_000
    assert boot["summary"]["expense_cents"] == expense_before + 6_000_000
    payment = next(tx for tx in boot["transactions"] if tx["id"] == debt["transaction_id"])
    assert payment["kind"] == "expense" and payment["category_id"] == food["id"] and "Budi" in payment["description"]

    # Undo removes the expense again.
    assert client.post(f"/api/debts/{debt_id}/unsettle").status_code == 200
    boot = boot_data(client)
    assert balance_of(boot, "Cash") == cash_before and boot["summary"]["expense_cents"] == expense_before
    assert boot["debts"][0]["settled"] is False and not any(tx["id"] == payment["id"] for tx in boot["transactions"])

    # Deleting the payment from Transaksi reopens the debt.
    client.post(f"/api/debts/{debt_id}/settle", json={"account_id": cash["id"]})
    tx_id = boot_data(client)["debts"][0]["transaction_id"]
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 200
    assert boot_data(client)["debts"][0]["settled"] is False

    assert client.delete(f"/api/debts/{debt_id}").status_code == 200
    assert client.delete(f"/api/debts/{debt_id}").status_code == 404
    assert boot_data(client)["debts"] == []


def test_others_debt_moves_balance_without_income_or_expense(client):
    boot = boot_data(client)
    cash = next(a for a in boot["accounts"] if a["name"] == "Cash")
    other = next(a for a in boot["accounts"] if a["id"] != cash["id"])
    summary, cash_before, tx_count = boot["summary"], cash["balance_cents"], len(boot["transactions"])

    base = {"direction": "theirs", "name": "Sari", "amount": "75000", "account_id": cash["id"]}
    assert client.post("/api/debts", json=base | {"account_id": ""}).status_code == 400
    debt_id = client.post("/api/debts", json=base).get_json()["id"]
    boot = boot_data(client)
    assert balance_of(boot, "Cash") == cash_before - 7_500_000
    assert boot["summary"]["assets_cents"] == summary["assets_cents"] - 7_500_000
    assert (boot["summary"]["income_cents"], boot["summary"]["expense_cents"]) == (summary["income_cents"], summary["expense_cents"])
    assert boot["daily"][-1]["assets_cents"] == boot["summary"]["assets_cents"]  # asset line agrees
    assert len(boot["transactions"]) == tx_count
    # The money has to come back somewhere: the account cannot be archived meanwhile.
    assert client.delete(f"/api/accounts/{cash['id']}", json={"destination_id": other["id"]}).status_code == 409

    assert client.post(f"/api/debts/{debt_id}/settle", json={}).status_code == 200
    boot = boot_data(client)
    assert boot["debts"][0]["settled"] and boot["debts"][0]["account"] == "Cash"
    assert balance_of(boot, "Cash") == cash_before
    assert boot["summary"]["income_cents"] == summary["income_cents"]  # not income
    assert boot["daily"][-1]["assets_cents"] == boot["summary"]["assets_cents"]
    assert len(boot["transactions"]) == tx_count

    assert client.post(f"/api/debts/{debt_id}/unsettle").status_code == 200
    assert balance_of(boot_data(client), "Cash") == cash_before - 7_500_000
    assert client.delete(f"/api/debts/{debt_id}").status_code == 200  # recorded by mistake: money back
    assert balance_of(boot_data(client), "Cash") == cash_before


def test_debts_belong_to_the_active_profile(client, data_dir):
    import local_store

    food = next(c for c in boot_data(client)["categories"] if c["kind"] == "expense")
    client.post("/api/debts", json={"direction": "mine", "name": "Budi", "amount": "1000", "category_id": food["id"]})
    usaha = next(p for p in client.post("/api/profiles", json={"name": "Usaha"}).get_json()["profiles"] if p["name"] == "Usaha")
    boot = boot_data(client)
    assert boot["debts"] == []
    cash = next(a for a in boot["accounts"] if a["name"] == "Cash")
    client.post("/api/debts", json={"direction": "theirs", "name": "Klien", "amount": "2000", "account_id": cash["id"]})
    assert client.get(f"/api/profiles/{usaha['id']}/summary").get_json()["counts"]["debts"] == 1
    client.delete(f"/api/profiles/{usaha['id']}")
    assert [item["name"] for item in boot_data(client)["debts"]] == ["Budi"]
    assert not any(usaha["id"] in key and docs for key, docs in local_store.local_client().data.items())


def test_migration_copies_debts_and_remaps_accounts(tmp_path):
    local, remote = LocalClient(tmp_path / "local.json"), LocalClient(tmp_path / "remote.json")
    local.collection("accounts").document("L-cash").set({"name": "Cash", "active": True})
    remote.collection("accounts").document("R-cash").set({"name": " cash ", "active": True})
    local.collection("debts").document("d1").set({"direction": "theirs", "name": "Sari", "amount_cents": 100, "account_id": "L-cash"})
    local.collection("debts").document("d2").set({"direction": "mine", "name": "Lokal", "amount_cents": 7})
    remote.collection("debts").document("d2").set({"direction": "mine", "name": "Sudah ada", "amount_cents": 5})
    report = migrate(local, remote)
    assert report["debts"] == {"copied": 1, "merged": 0, "skipped": 1}
    assert remote.collection("debts").document("d1").get().to_dict()["account_id"] == "R-cash"
    assert remote.collection("debts").document("d2").get().to_dict()["name"] == "Sudah ada"


def test_settings_endpoints_are_gone(client):
    assert client.get("/api/settings").status_code == 404
    assert client.post("/api/settings/migration", json={"action": "migrate"}).status_code in (404, 405)


def test_remember_me_controls_cookie_lifetime(data_dir, monkeypatch):
    """Without "Ingat saya" the login cookie ends with the browser; with it, it lasts 30 days."""
    import app as app_module

    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-pass")
    web = app_module.app.test_client()
    short = web.post("/api/login", json={"password": "test-pass"}).headers.get("Set-Cookie", "")
    long = web.post("/api/login", json={"password": "test-pass", "remember": True}).headers.get("Set-Cookie", "")
    assert "Expires=" not in short
    from datetime import datetime, timedelta, timezone
    from email.utils import parsedate_to_datetime

    expires = parsedate_to_datetime(long.split("Expires=")[1].split(";")[0])
    assert abs(expires - (datetime.now(timezone.utc) + timedelta(days=30))) < timedelta(minutes=5)
