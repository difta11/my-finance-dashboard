"""My Finance Dashboard: single-owner Flask app backed by Firebase."""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import secrets
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import HTTPException

from firebase_store import create_record, delete_record, firestore_client, get_record, list_records, storage_bucket

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
IS_VERCEL = os.getenv("VERCEL", "").lower() == "1"
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
app = Flask(__name__, static_folder=None)
app.secret_key = SESSION_SECRET or secrets.token_hex(32)
try:
    requested_upload_mb = max(1, int(os.getenv("MAX_UPLOAD_MB", "4")))
except ValueError:
    requested_upload_mb = 4
# Vercel Functions reject request bodies above 4.5 MB, including multipart overhead.
app.config["MAX_UPLOAD_MB"] = min(requested_upload_mb, 4) if IS_VERCEL else requested_upload_mb
app.config["MAX_UPLOAD_BYTES"] = app.config["MAX_UPLOAD_MB"] * 1024 * 1024
# Allow room for multipart boundaries while staying below Vercel's 4.5 MB body cap.
app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_UPLOAD_BYTES"] + 256 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Mobile devices reach the local app over plain HTTP on the LAN. Secure
    # cookies are enabled for the HTTPS Vercel deployment only.
    SESSION_COOKIE_SECURE=IS_VERCEL,
)

JAKARTA = ZoneInfo("Asia/Jakarta")
EXPENSES = ["Makanan & Minuman", "Transportasi", "Bensin", "Belanja", "Tagihan", "Hiburan", "Kesehatan", "Pendidikan", "Tempat Tinggal", "Langganan", "Lainnya"]
INCOMES = ["Gaji", "Bonus", "Freelance", "Bisnis", "Investasi", "Hadiah", "Lainnya"]


def now_local() -> datetime:
    return datetime.now(JAKARTA).replace(tzinfo=None)


def stamp_now() -> str:
    return now_local().isoformat(timespec="seconds")


def money(value, allow_zero=False):
    try:
        raw = re.sub(r"\s|Rp", "", str(value), flags=re.I)
        if not re.fullmatch(r"\d+", raw):
            raise ValueError()
        cents = int(raw) * 100
        if cents < (0 if allow_zero else 1) or cents > 10**15:
            raise ValueError()
        return cents
    except (InvalidOperation, ValueError):
        raise ValueError("Nominal harus angka positif")


def normalize_account_name(value):
    """Normalize spacing, compatibility characters, and case for account names."""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def parse_ai_amount(value):
    """Normalize model amounts such as 25000, 25.000, 50rb, or 8,5jt to IDR."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = int(value)
        return amount if amount > 0 else None
    raw = str(value).lower().replace("rp", "").replace(" ", "").strip()
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        amount = int(re.sub(r"[.,]", "", raw))
        return amount if 0 < amount <= 10**13 else None
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|m)?", raw)
    if not match:
        return None
    number = Decimal(match.group(1).replace(",", "."))
    suffix = match.group(2)
    multiplier = 1_000_000 if suffix in ("jt", "juta", "m") else 1_000 if suffix in ("rb", "ribu", "k") else 1
    amount = int(number * multiplier)
    return amount if 0 < amount <= 10**13 else None


def ensure_defaults(accounts, categories):
    account_names = {item["name"].casefold() for item in accounts}
    category_keys = {(item["name"].casefold(), item["kind"]) for item in categories}
    timestamp = stamp_now()
    pending = []
    for name, kind in [("Cash", "cash"), ("Bank Jago", "bank"), ("Mandiri", "bank"), ("GoPay", "ewallet")]:
        if name.casefold() not in account_names:
            record = {"name": name, "kind": kind, "initial_cents": 0, "active": True, "created_at": timestamp}
            pending.append(("accounts", record, accounts))
            account_names.add(name.casefold())
    for name in EXPENSES:
        if (name.casefold(), "expense") not in category_keys:
            record = {"name": name, "kind": "expense", "color": "#8794ff", "active": True}
            pending.append(("categories", record, categories))
            category_keys.add((name.casefold(), "expense"))
    for name in INCOMES:
        if (name.casefold(), "income") not in category_keys:
            record = {"name": name, "kind": "income", "color": "#8794ff", "active": True}
            pending.append(("categories", record, categories))
            category_keys.add((name.casefold(), "income"))
    if pending:
        client = firestore_client()
        batch = client.batch()
        for collection, record, destination in pending:
            ref = client.collection(collection).document()
            batch.set(ref, record)
            destination.append(record | {"id": ref.id})
        batch.commit()
    return accounts, categories


def account_balance(account, transactions, before=None):
    if not account:
        return 0
    account_id = str(account["id"])
    created = str(account.get("created_at", ""))[:10]
    total = int(account.get("initial_cents", 0) or 0) if not before or created < before else 0
    for tx in transactions:
        if before and str(tx.get("occurred_at", ""))[:10] >= before:
            continue
        amount = int(tx.get("amount_cents", 0) or 0)
        kind = tx.get("kind")
        if kind == "income" and str(tx.get("account_id")) == account_id:
            total += amount
        elif kind == "expense" and str(tx.get("account_id")) == account_id:
            total -= amount
        elif kind == "transfer":
            if str(tx.get("account_id")) == account_id:
                total -= amount
            if str(tx.get("destination_id")) == account_id:
                total += amount
    return total


def active_accounts_and_transactions():
    # Initialize the cached Admin clients before starting parallel reads.
    firestore_client()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {collection: pool.submit(list_records, collection) for collection in ("accounts", "categories", "transactions", "wishes", "budgets")}
        accounts = futures["accounts"].result()
        categories = futures["categories"].result()
        transactions = futures["transactions"].result()
        wishes = futures["wishes"].result()
        budgets = futures["budgets"].result()
    accounts, categories = ensure_defaults(accounts, categories)
    return accounts, categories, transactions, wishes, budgets


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("ok"):
            if not request.path.startswith("/api/"):
                return redirect(url_for("login_page"))
            return jsonify(error="Silakan login"), 401
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-CSRF-Token") != session.get("csrf"):
            return jsonify(error="Token keamanan sesi telah diperbarui. Coba ulangi aksi.", csrf=session.get("csrf")), 403
        return fn(*args, **kwargs)
    return wrapped


@app.get("/static/<path:filename>")
def local_static(filename):
    # Vercel serves public assets directly; this route supports local Flask use.
    return send_from_directory(ROOT / "public" / "static", filename)


@app.get("/login")
def login_page():
    return render_template("login.html")


@app.post("/api/login")
def login():
    password = os.getenv("DASHBOARD_PASSWORD", "")
    if IS_VERCEL and not SESSION_SECRET:
        return jsonify(error="Atur SESSION_SECRET pada environment Vercel sebelum login."), 503
    if not password:
        return jsonify(error="Atur DASHBOARD_PASSWORD pada environment sebelum login."), 503
    if not secrets.compare_digest(password, str((request.json or {}).get("password", ""))):
        return jsonify(error="Kata sandi salah"), 401
    session.clear()
    session["ok"] = True
    session["csrf"] = secrets.token_urlsafe(24)
    return jsonify(ok=True, csrf=session["csrf"])


@app.get("/api/session")
def session_status():
    return jsonify(authenticated=bool(session.get("ok")))


@app.post("/api/logout")
@login_required
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/")
@login_required
def home():
    html = render_template("index.html")
    return html.replace("<body>", f'<body data-max-upload-mb="{app.config["MAX_UPLOAD_MB"]}">', 1)


@app.get("/api/bootstrap")
@login_required
def bootstrap():
    try:
        accounts, categories, transactions, wishes, budgets = active_accounts_and_transactions()
        today = now_local().date()
        end = request.args.get("end", today.isoformat())
        start = request.args.get("start", today.replace(day=1).isoformat())
        try:
            wish_today = date.fromisoformat(request.args.get("today", today.isoformat()))
        except ValueError:
            wish_today = date.today()
        all_transactions = start == "0001-01-01"
        if all_transactions:
            dates = [str(tx.get("occurred_at", ""))[:10] for tx in transactions if tx.get("occurred_at")]
            start = min(dates) if dates else end
            end = max([end, *dates]) if dates else end
        try:
            start_day = date.fromisoformat(start)
            end_day = date.fromisoformat(end)
        except ValueError:
            return jsonify(error="Rentang tanggal tidak valid"), 400
        if end_day < start_day:
            return jsonify(error="Tanggal akhir harus sama atau setelah tanggal mulai"), 400

        active_accounts = [a for a in accounts if a.get("active", True)]
        active_categories = [c for c in categories if c.get("active", True)]
        category_by_id = {str(c["id"]): c for c in categories}
        account_by_id = {str(a["id"]): a for a in accounts}
        accts = [a | {"balance_cents": account_balance(a, transactions)} for a in active_accounts]
        tx_counts = {}
        for tx in transactions:
            if tx.get("category_id"):
                key = str(tx["category_id"])
                tx_counts[key] = tx_counts.get(key, 0) + 1
        cats = [c | {"transaction_count": tx_counts.get(str(c["id"]), 0)} for c in active_categories]

        active_budgets = []
        for budget in budgets:
            if not budget.get("active", True):
                continue
            budget_category_id = str(budget.get("category_id", ""))
            category = category_by_id.get(budget_category_id, {})
            account = account_by_id.get(str(budget.get("account_id", "")), {})
            created_at = str(budget.get("created_at", ""))
            spent = sum(
                int(tx.get("amount_cents", 0) or 0)
                for tx in transactions
                if tx.get("kind") == "expense"
                and str(tx.get("category_id", "")) == budget_category_id
                and str(tx.get("created_at") or tx.get("occurred_at") or "") >= created_at
            )
            allocated = int(budget.get("allocated_cents", 0) or 0)
            remaining = max(0, allocated - spent)
            active_budgets.append(budget | {
                "category": category.get("name", "Kategori diarsipkan"),
                "account": account.get("name", "Akun diarsipkan"),
                "spent_cents": spent,
                "remaining_cents": remaining,
                "remaining_percent": round(remaining / allocated * 100) if allocated else 0,
                "overspent_cents": max(0, spent - allocated),
            })
        active_budgets.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))), reverse=True)

        in_range = [tx for tx in transactions if start <= str(tx.get("occurred_at", ""))[:10] <= end]
        in_range.sort(key=lambda tx: (str(tx.get("occurred_at", "")), str(tx.get("id", ""))), reverse=True)
        if not all_transactions:
            in_range = in_range[:500]
        rows = []
        for tx in in_range:
            category = category_by_id.get(str(tx.get("category_id")), {})
            account = account_by_id.get(str(tx.get("account_id")), {})
            destination = account_by_id.get(str(tx.get("destination_id")), {})
            rows.append(tx | {"category": category.get("name"), "account": account.get("name"), "destination": destination.get("name")})

        period_transactions = [tx for tx in transactions if start <= str(tx.get("occurred_at", ""))[:10] <= end]
        income = sum(int(tx.get("amount_cents", 0)) for tx in period_transactions if tx.get("kind") == "income")
        expense = sum(int(tx.get("amount_cents", 0)) for tx in period_transactions if tx.get("kind") == "expense")
        bycat = {}
        for tx in period_transactions:
            if tx.get("kind") == "expense":
                name = category_by_id.get(str(tx.get("category_id")), {}).get("name") or "Lainnya"
                bycat[name] = bycat.get(name, 0) + int(tx.get("amount_cents", 0))

        active_ids = {str(a["id"]) for a in active_accounts}
        opening_assets = sum(int(a.get("initial_cents", 0)) for a in active_accounts if str(a.get("created_at", ""))[:10] < start)
        for tx in transactions:
            if str(tx.get("occurred_at", ""))[:10] >= start:
                continue
            amount = int(tx.get("amount_cents", 0))
            if tx.get("kind") == "income" and str(tx.get("account_id")) in active_ids:
                opening_assets += amount
            elif tx.get("kind") == "expense" and str(tx.get("account_id")) in active_ids:
                opening_assets -= amount
            elif tx.get("kind") == "transfer":
                if str(tx.get("account_id")) in active_ids:
                    opening_assets -= amount
                if str(tx.get("destination_id")) in active_ids:
                    opening_assets += amount

        daily_map = {}
        for account in active_accounts:
            created = str(account.get("created_at", ""))[:10]
            if start <= created <= end:
                daily_map.setdefault(created, {"income_cents": 0, "expense_cents": 0, "delta_cents": 0})["delta_cents"] += int(account.get("initial_cents", 0))
        for tx in period_transactions:
            day = str(tx.get("occurred_at", ""))[:10]
            point = daily_map.setdefault(day, {"income_cents": 0, "expense_cents": 0, "delta_cents": 0})
            amount = int(tx.get("amount_cents", 0))
            if tx.get("kind") == "income":
                point["income_cents"] += amount
                if str(tx.get("account_id")) in active_ids:
                    point["delta_cents"] += amount
            elif tx.get("kind") == "expense":
                point["expense_cents"] += amount
                if str(tx.get("account_id")) in active_ids:
                    point["delta_cents"] -= amount
            else:
                if str(tx.get("account_id")) in active_ids:
                    point["delta_cents"] -= amount
                if str(tx.get("destination_id")) in active_ids:
                    point["delta_cents"] += amount
        daily = []
        if (end_day - start_day).days <= 36525:
            assets = opening_assets
            day = start_day
            while day <= end_day:
                day_text = day.isoformat()
                point = daily_map.get(day_text, {"income_cents": 0, "expense_cents": 0, "delta_cents": 0})
                assets += point["delta_cents"]
                daily.append({"date": day_text, "assets_cents": assets, "expense_cents": point["expense_cents"]})
                day += timedelta(days=1)

        wish_days = 90
        wish_end = wish_today.isoformat()
        wish_start = (wish_today - timedelta(days=wish_days - 1)).isoformat()
        assets_before = sum(account_balance(a, transactions, before=wish_start) for a in active_accounts)
        wish_income = sum(int(tx.get("amount_cents", 0)) for tx in transactions if tx.get("kind") == "income" and wish_start <= str(tx.get("occurred_at", ""))[:10] <= wish_end)
        wish_expense = sum(int(tx.get("amount_cents", 0)) for tx in transactions if tx.get("kind") == "expense" and wish_start <= str(tx.get("occurred_at", ""))[:10] <= wish_end)
        current_assets = sum(a["balance_cents"] for a in accts)
        wish_stats = {"period_days": wish_days, "current_assets_cents": current_assets, "income_90d_cents": wish_income, "expense_90d_cents": wish_expense, "asset_change_90d_cents": current_assets - assets_before}
        wishes.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))), reverse=True)
        return jsonify(accounts=accts, categories=cats, budgets=active_budgets, wishes=wishes, wish_stats=wish_stats, transactions=rows, csrf=session.get("csrf"), range_start=start, range_end=end, daily=daily, summary={"assets_cents": current_assets, "income_cents": income, "expense_cents": expense, "net_cents": income - expense, "categories": bycat})
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503


@app.route("/api/accounts", methods=["POST"])
@login_required
def accounts_api():
    data = request.json or {}
    name = " ".join(str(data.get("name", "")).split())
    kind = data.get("kind", "bank")
    if not name or len(name) > 80:
        return jsonify(error="Nama akun wajib diisi (maks. 80 karakter)"), 400
    if kind not in ("cash", "bank", "ewallet", "other"):
        return jsonify(error="Jenis akun tidak valid"), 400
    try:
        initial = money(data.get("initial_balance", 0), allow_zero=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    matches = [a for a in list_records("accounts") if normalize_account_name(a.get("name", "")) == normalize_account_name(name)]
    active_match = next((a for a in matches if a.get("active", True)), None)
    archived_match = next((a for a in matches if not a.get("active", True)), None)
    if active_match:
        return jsonify(error=f'Akun "{active_match.get("name", name)}" sudah ada.'), 409
    if archived_match:
        firestore_client().collection("accounts").document(archived_match["id"]).update({
            "name": name,
            "kind": kind,
            "initial_cents": initial,
            "active": True,
            "created_at": stamp_now(),
        })
        return jsonify(ok=True, reactivated=True)
    create_record("accounts", {"name": name, "kind": kind, "initial_cents": initial, "active": True, "created_at": stamp_now()})
    return jsonify(ok=True)


@app.delete("/api/accounts/<account_id>")
@login_required
def delete_account(account_id):
    data = request.json or {}
    destination_id = str(data.get("destination_id", ""))
    accounts, _, transactions, _, budgets = active_accounts_and_transactions()
    account = next((item for item in accounts if item["id"] == account_id and item.get("active", True)), None)
    if not account:
        return jsonify(error="Akun tidak ditemukan"), 404
    if any(budget.get("active", True) and str(budget.get("account_id")) == account_id for budget in budgets):
        return jsonify(error="Akun ini menjadi sumber budget. Hapus budget terkait sebelum menghapus akun."), 409
    if len([item for item in accounts if item.get("active", True)]) <= 1:
        return jsonify(error="Akun aktif terakhir tidak dapat dihapus"), 409
    current_balance = account_balance(account, transactions)
    if current_balance:
        if not destination_id or destination_id == account_id:
            return jsonify(error="Pilih akun tujuan yang berbeda untuk mengalihkan saldo"), 400
        destination = next((item for item in accounts if item["id"] == destination_id and item.get("active", True)), None)
        if not destination:
            return jsonify(error="Akun tujuan tidak ditemukan"), 400
    client = firestore_client()
    batch = client.batch()
    batch.update(client.collection("accounts").document(account_id), {"active": False})
    if current_balance:
        source_id, target_id = (account_id, destination_id) if current_balance > 0 else (destination_id, account_id)
        ref = client.collection("transactions").document()
        batch.set(ref, {"kind": "transfer", "amount_cents": abs(current_balance), "category_id": None, "account_id": source_id, "destination_id": target_id, "description": "Pengalihan saldo akun: " + account["name"], "payment_method": "Transfer internal", "original_input": "Penghapusan akun", "occurred_at": str(data.get("occurred_at") or stamp_now()), "created_at": stamp_now(), "receipt_file": None})
    batch.commit()
    return jsonify(ok=True)


@app.route("/api/categories", methods=["POST"])
@login_required
def categories_api():
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    kind = data.get("kind")
    if not name or len(name) > 60 or kind not in ("income", "expense"):
        return jsonify(error="Nama kategori (maks. 60 karakter) dan jenis wajib diisi"), 400
    if any(c.get("name", "").casefold() == name.casefold() and c.get("kind") == kind for c in list_records("categories")):
        return jsonify(error="Kategori sudah ada"), 409
    create_record("categories", {"name": name, "kind": kind, "color": "#8794ff", "active": True})
    return jsonify(ok=True)


@app.put("/api/categories/<category_id>")
@login_required
def update_category(category_id):
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 60:
        return jsonify(error="Nama kategori wajib diisi (maks. 60 karakter)"), 400
    categories = list_records("categories")
    category = next((item for item in categories if item["id"] == category_id and item.get("active", True)), None)
    if not category:
        return jsonify(error="Kategori tidak ditemukan"), 404
    if any(item["id"] != category_id and item.get("kind") == category["kind"] and item.get("name", "").casefold() == name.casefold() for item in categories):
        return jsonify(error="Kategori dengan nama tersebut sudah ada"), 409
    firestore_client().collection("categories").document(category_id).update({"name": name})
    return jsonify(ok=True)


@app.delete("/api/categories/<category_id>")
@login_required
def delete_category(category_id):
    categories = list_records("categories")
    if not any(item["id"] == category_id and item.get("active", True) for item in categories):
        return jsonify(error="Kategori tidak ditemukan"), 404
    if any(str(tx.get("category_id")) == category_id for tx in list_records("transactions")):
        return jsonify(error="Kategori yang masih dipakai transaksi tidak dapat dihapus"), 409
    if any(budget.get("active", True) and str(budget.get("category_id")) == category_id for budget in list_records("budgets")):
        return jsonify(error="Kategori yang masih dipakai budget tidak dapat dihapus"), 409
    delete_record("categories", category_id)
    return jsonify(ok=True)


@app.post("/api/wishes")
@login_required
def create_wish():
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 80:
        return jsonify(error="Nama impian wajib diisi (maks. 80 karakter)"), 400
    try:
        target = money(data.get("target"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    create_record("wishes", {"name": name, "target_cents": target, "created_at": stamp_now()})
    return jsonify(ok=True)


@app.delete("/api/wishes/<wish_id>")
@login_required
def delete_wish(wish_id):
    if not get_record("wishes", wish_id):
        return jsonify(error="Impian tidak ditemukan"), 404
    delete_record("wishes", wish_id)
    return jsonify(ok=True)


@app.post("/api/budgets")
@login_required
def create_budget():
    data = request.json or {}
    name = " ".join(str(data.get("name", "")).split())
    account_id = str(data.get("account_id", ""))
    category_id = str(data.get("category_id", ""))
    if not name or len(name) > 80:
        return jsonify(error="Nama budget wajib diisi (maks. 80 karakter)"), 400
    try:
        allocated = money(data.get("amount"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    account = get_record("accounts", account_id)
    if not account or not account.get("active", True):
        return jsonify(error="Pilih akun sumber yang aktif"), 400
    category = get_record("categories", category_id)
    if not category or not category.get("active", True) or category.get("kind") != "expense":
        return jsonify(error="Pilih kategori pengeluaran yang aktif"), 400
    budgets = list_records("budgets")
    if any(item.get("active", True) and str(item.get("category_id")) == category_id for item in budgets):
        return jsonify(error="Kategori ini sudah terhubung ke budget lain"), 409
    create_record("budgets", {
        "name": name,
        "account_id": account_id,
        "category_id": category_id,
        "allocated_cents": allocated,
        "active": True,
        "created_at": stamp_now(),
    })
    return jsonify(ok=True)


@app.delete("/api/budgets/<budget_id>")
@login_required
def delete_budget(budget_id):
    budget = get_record("budgets", budget_id)
    if not budget or not budget.get("active", True):
        return jsonify(error="Budget tidak ditemukan"), 404
    delete_record("budgets", budget_id)
    return jsonify(ok=True)


@app.route("/api/transactions", methods=["POST"])
@login_required
def create_transaction():
    data = request.json or {}
    kind = data.get("kind")
    account_id = str(data.get("account_id", ""))
    destination_id = str(data.get("destination_id", ""))
    receipt_file = str(data.get("receipt_file", "")).strip()
    if receipt_file and not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", receipt_file):
        return jsonify(error="Foto struk tidak ditemukan. Unggah ulang struk sebelum menyimpan."), 400
    if kind not in ("income", "expense", "transfer"):
        return jsonify(error="Jenis transaksi tidak valid"), 400
    if not account_id or (kind == "transfer" and (not destination_id or account_id == destination_id)):
        return jsonify(error="Pilih akun yang valid"), 400
    try:
        cents = money(data.get("amount"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    accounts = list_records("accounts")
    active_by_id = {item["id"]: item for item in accounts if item.get("active", True)}
    if account_id not in active_by_id or (kind == "transfer" and destination_id not in active_by_id):
        return jsonify(error="Akun tidak ditemukan"), 400
    category_id = None
    if kind != "transfer":
        category_id = str(data.get("category_id", ""))
        if not category_id:
            return jsonify(error="Kategori tidak valid"), 400
        category = get_record("categories", category_id)
        if not category or not category.get("active", True) or category.get("kind") != kind:
            return jsonify(error="Kategori tidak valid"), 400
    draft_blob = None
    saved_blob = None
    if receipt_file:
        bucket = storage_bucket()
        draft_blob = bucket.blob("draft-receipts/" + receipt_file)
        if not draft_blob.exists():
            return jsonify(error="Foto struk tidak ditemukan. Unggah ulang struk sebelum menyimpan."), 400
        saved_blob = bucket.blob("receipts/" + receipt_file)
        bucket.copy_blob(draft_blob, bucket, new_name=saved_blob.name)
        draft_blob.delete()
    occurred_at = str(data.get("occurred_at") or stamp_now())
    record = {"kind": kind, "amount_cents": cents, "category_id": category_id, "account_id": account_id, "destination_id": destination_id if kind == "transfer" else None, "description": str(data.get("description", ""))[:300], "payment_method": str(data.get("payment_method", ""))[:50], "original_input": str(data.get("original_input", ""))[:1000], "occurred_at": occurred_at, "created_at": stamp_now(), "receipt_file": receipt_file or None}
    try:
        create_record("transactions", record)
    except Exception:
        if saved_blob and saved_blob.exists():
            saved_blob.delete()
        raise
    return jsonify(ok=True)


@app.patch("/api/transactions/<transaction_id>")
@login_required
def update_transaction(transaction_id):
    data = request.json or {}
    tx = get_record("transactions", transaction_id)
    if not tx:
        return jsonify(error="Transaksi tidak ditemukan"), 404
    updates = {}
    if "account_id" in data:
        account_id = str(data.get("account_id", ""))
        account = get_record("accounts", account_id)
        if not account or not account.get("active", True):
            return jsonify(error="Pilih akun sumber yang aktif"), 400
        if tx.get("kind") == "transfer" and account_id == str(tx.get("destination_id")):
            return jsonify(error="Akun sumber tidak boleh sama dengan akun tujuan"), 400
        updates["account_id"] = account_id
    if "category_id" in data:
        if tx.get("kind") == "transfer":
            return jsonify(error="Transaksi transfer tidak memiliki kategori"), 400
        category = get_record("categories", str(data.get("category_id", "")))
        if not category or not category.get("active", True) or category.get("kind") != tx.get("kind"):
            return jsonify(error="Pilih kategori aktif dengan jenis transaksi yang sesuai"), 400
        updates["category_id"] = category["id"]
    if not updates:
        return jsonify(error="Tidak ada perubahan yang dikirim"), 400
    firestore_client().collection("transactions").document(transaction_id).update(updates)
    return jsonify(ok=True)


@app.delete("/api/transactions/<transaction_id>")
@login_required
def delete_transaction(transaction_id):
    tx = get_record("transactions", transaction_id)
    if not tx:
        return jsonify(error="Transaksi tidak ditemukan"), 404
    delete_record("transactions", transaction_id)
    if tx.get("receipt_file"):
        blob = storage_bucket().blob("receipts/" + tx["receipt_file"])
        if blob.exists():
            blob.delete()
    return jsonify(ok=True)


@app.get("/api/receipts/<filename>")
@login_required
def get_receipt(filename):
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", filename):
        return jsonify(error="Foto struk tidak ditemukan"), 404
    if not any(tx.get("receipt_file") == filename for tx in list_records("transactions")):
        return jsonify(error="Foto struk tidak ditemukan"), 404
    blob = storage_bucket().blob("receipts/" + filename)
    if not blob.exists():
        return jsonify(error="Foto struk tidak ditemukan"), 404
    content_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[filename.rsplit(".", 1)[1]]
    return Response(blob.download_as_bytes(), mimetype=content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/export.csv")
@login_required
def export_csv():
    _, categories, transactions, _, _ = active_accounts_and_transactions()
    accounts = list_records("accounts")
    category_by_id = {str(item["id"]): item.get("name") for item in categories}
    account_by_id = {str(item["id"]): item.get("name") for item in accounts}
    transactions.sort(key=lambda item: (str(item.get("occurred_at", "")), str(item.get("id", ""))), reverse=True)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Tanggal", "Jenis", "Nominal (IDR)", "Kategori", "Akun", "Tujuan", "Deskripsi", "Metode", "Input asli"])
    for tx in transactions:
        writer.writerow([tx.get("occurred_at", ""), tx.get("kind", ""), Decimal(int(tx.get("amount_cents", 0))) / 100, category_by_id.get(str(tx.get("category_id"))), account_by_id.get(str(tx.get("account_id"))), account_by_id.get(str(tx.get("destination_id"))), tx.get("description", ""), tx.get("payment_method", ""), tx.get("original_input", "")])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=transaksi.csv"})


@app.post("/api/parse")
@login_required
def parse_ai():
    if os.getenv("AI_ENABLED", "false").lower() != "true":
        return jsonify(error="AI belum aktif. Atur AI_ENABLED=true pada environment."), 503
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider not in ("gemini", "openai"):
        return jsonify(error="AI_PROVIDER harus bernilai gemini atau openai."), 503
    api_key = os.getenv("GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY", "")
    if not api_key:
        return jsonify(error=f"API key {provider} belum diatur pada environment."), 503
    data = request.form if request.mimetype == "multipart/form-data" else (request.json or {})
    text = str(data.get("text", ""))[:3000]
    image = request.files.get("receipt") if request.files else None
    image_data = None
    image_mime = None
    image_extension = None
    categories = [item for item in list_records("categories") if item.get("active", True)]
    accounts = [item for item in list_records("accounts") if item.get("active", True)]
    budgets = list_records("budgets")
    category_guide = "\nKategori aktif (gunakan nama dan jenis persis dari daftar ini): " + json.dumps([{"name": item["name"], "kind": item["kind"]} for item in categories], ensure_ascii=False)
    category_by_id = {str(item["id"]): item for item in categories}
    budget_guide = "\nBudget aktif dan kategori penghubungnya (bila deskripsi jelas merujuk budget, pilih kategori penghubungnya): " + json.dumps([{"name": item.get("name", ""), "category": category_by_id.get(str(item.get("category_id", "")), {}).get("name", "")} for item in budgets if item.get("active", True)], ensure_ascii=False)
    account_names = [item["name"] for item in accounts]
    account_guide = "\nAkun aktif yang tersedia: " + json.dumps(account_names, ensure_ascii=False)
    user_text = "Ekstrak satu transaksi ke JSON untuk draft; jangan mengarang. Field: type (income|expense|transfer), amount (nominal rupiah integer, gunakan 0 jika tidak diketahui), category (nama kategori tersedia atau Transfer), account (nama akun aktif yang membayar/menerima, atau string kosong), destination_account (akun tujuan transfer, atau string kosong), description, payment_method (metode seperti QRIS, tunai, debit; string kosong jika tidak disebut), occurred_at (ISO atau string kosong bila tanggal tidak disebut), confidence (0-1), question (string kosong atau pertanyaan klarifikasi). Bedakan nama metode pembayaran dari nama akun. Jika input menyebut 'QRIS Mandiri', isi payment_method='QRIS' dan account='Mandiri' bila Mandiri ada di daftar akun. Pilih kategori custom paling cocok secara makna dari daftar, jangan membuat kategori baru. Jangan menebak akun atau metode yang tidak disebut." + category_guide + budget_guide + account_guide + ("\nInput: " + text if text else "\nBaca struk berikut.")
    if image and image.filename:
        if image.mimetype not in ("image/jpeg", "image/png", "image/webp"):
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        image_data = image.read()
        if len(image_data) > app.config["MAX_UPLOAD_BYTES"]:
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        image_mime = image.mimetype
        image_extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[image_mime]
    try:
        prompt = (ROOT / "prompts" / "transaction-extraction.md").read_text(encoding="utf-8")
        if provider == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=2)))
            contents = [user_text]
            if image_data:
                contents.append(types.Part.from_bytes(data=image_data, mime_type=image_mime))
            schema = {"type": "OBJECT", "properties": {"type": {"type": "STRING", "enum": ["income", "expense", "transfer"]}, "amount": {"type": "INTEGER"}, "category": {"type": "STRING"}, "account": {"type": "STRING"}, "destination_account": {"type": "STRING"}, "description": {"type": "STRING"}, "payment_method": {"type": "STRING"}, "occurred_at": {"type": "STRING"}, "confidence": {"type": "NUMBER"}, "question": {"type": "STRING"}}, "required": ["type", "amount", "category", "account", "destination_account", "description", "payment_method", "occurred_at", "confidence", "question"]}
            response = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), contents=contents, config=types.GenerateContentConfig(system_instruction=prompt, response_mime_type="application/json", response_schema=schema, temperature=0.1))
            result = json.loads(response.text or "")
        else:
            content = [{"type": "text", "text": user_text}]
            if image_data:
                payload = base64.b64encode(image_data).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{payload}"}})
            response = requests.post(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + api_key}, json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": prompt + " Jawab JSON valid saja."}, {"role": "user", "content": content}]}, timeout=35)
            if not response.ok:
                error_body = response.json().get("error", {})
                detail = (error_body.get("message") or "").strip()
                code = error_body.get("code") or error_body.get("type") or ""
                app.logger.warning("OpenAI API returned HTTP %s (%s): %s", response.status_code, code, detail[:300])
                if response.status_code == 401:
                    return jsonify(error="API key OpenAI ditolak. Periksa OPENAI_API_KEY."), 502
                if response.status_code == 429 and code in ("insufficient_quota", "credit_balance_exhausted", "organization_usage_limit_exceeded", "organization_spend_limit_exceeded", "project_spend_limit_exceeded"):
                    return jsonify(error=f"Akses API dibatasi OpenAI (kode: {code}). Periksa saldo/billing API dan usage limit organisasi/project."), 502
                if response.status_code == 429:
                    return jsonify(error="OpenAI membatasi laju request. Tunggu sebentar lalu coba lagi."), 502
                if response.status_code == 404:
                    return jsonify(error="Model atau endpoint OpenAI tidak ditemukan. Periksa OPENAI_MODEL dan OPENAI_BASE_URL."), 502
                return jsonify(error="OpenAI menolak permintaan: " + (detail[:220] or f"HTTP {response.status_code}")), 502
            result = json.loads(response.json()["choices"][0]["message"]["content"])

        result["amount"] = parse_ai_amount(result.get("amount", result.get("amount_idr")))
        kind = result.get("type")
        if kind not in ("income", "expense", "transfer"):
            kind = "expense"
            result["type"] = kind
        valid_categories = [item["name"] for item in categories if item["kind"] == kind]
        if kind == "transfer":
            result["category"] = "Transfer"
        else:
            match = next((name for name in valid_categories if name.casefold() == str(result.get("category") or "").strip().casefold()), None)
            result["category"] = match or ("Lainnya" if "Lainnya" in valid_categories else (valid_categories[0] if valid_categories else None))
        result["account"] = next((name for name in account_names if name.casefold() == str(result.get("account") or "").strip().casefold()), None)
        result["destination_account"] = next((name for name in account_names if name.casefold() == str(result.get("destination_account") or "").strip().casefold()), None) if kind == "transfer" else None
        if text:
            normalized_text = text.casefold()
            mentioned_account = next((name for name in sorted(account_names, key=len, reverse=True) if name.casefold() in normalized_text), None)
            if kind != "transfer" and mentioned_account:
                result["account"] = mentioned_account
            for marker, method in (("qris", "QRIS"), ("tunai", "Tunai"), ("cash", "Tunai"), ("debit", "Debit"), ("kredit", "Kredit"), ("credit", "Kredit")):
                if marker in normalized_text:
                    result["payment_method"] = method
                    break
        result["question"] = result.get("question") or ("Nominal belum terbaca. Mohon lengkapi sebelum menyimpan." if not result["amount"] else None)
        result["needs_confirmation"] = True
        if image_data:
            receipt_file = secrets.token_hex(16) + image_extension
            try:
                blob = storage_bucket().blob("draft-receipts/" + receipt_file)
                blob.upload_from_string(image_data, content_type=image_mime)
            except Exception:
                app.logger.warning("Firebase Storage could not save the receipt draft; keeping the parsed transaction", exc_info=True)
                notice = "Foto struk berhasil dibaca, tetapi tidak tersimpan. Transaksi tetap bisa disimpan tanpa foto."
                result["question"] = (str(result["question"]).strip() + " · " if result.get("question") else "") + notice
            else:
                result["receipt_file"] = receipt_file
        return jsonify(draft=result)
    except requests.Timeout:
        return jsonify(error="Permintaan ke OpenAI melewati batas waktu. Coba lagi sebentar."), 504
    except requests.RequestException as exc:
        app.logger.warning("OpenAI connection failed: %s", str(exc)[:300])
        return jsonify(error="Tidak dapat terhubung ke OpenAI. Periksa koneksi internet dan OPENAI_BASE_URL."), 502
    except Exception as exc:
        if provider == "gemini":
            detail = str(exc)
            status = str(getattr(exc, "code", getattr(exc, "status_code", "")))
            app.logger.warning("Gemini request failed (%s): %s", status, detail[:300])
            if "timeout" in type(exc).__name__.lower() or "timed out" in detail.lower():
                return jsonify(error="Gemini tidak merespons dalam 30 detik. Coba lagi sebentar."), 504
            if status == "503" or "503" in detail or "SERVICE_UNAVAILABLE" in detail.upper() or "UNAVAILABLE" in detail.upper():
                return jsonify(error="Gemini sedang tidak tersedia (503). Layanan bisa sedang padat atau mengalami gangguan sementara. API key dan model belum tentu bermasalah; tunggu sebentar lalu coba lagi."), 503
            if status == "504" or "DEADLINE_EXCEEDED" in detail.upper():
                return jsonify(error="Gemini tidak merespons tepat waktu (504). Coba lagi sebentar."), 504
            if status == "429" or "RESOURCE_EXHAUSTED" in detail:
                return jsonify(error="Gemini menolak request karena quota/rate limit. Periksa quota project Google AI Studio dan model yang dipilih."), 502
            if status in ("401", "403") or "API_KEY_INVALID" in detail:
                return jsonify(error="API key Gemini tidak valid atau tidak memiliki akses. Periksa GEMINI_API_KEY."), 502
            if status == "404" or "NOT_FOUND" in detail:
                return jsonify(error="Model Gemini tidak ditemukan. Periksa GEMINI_MODEL di environment."), 502
            return jsonify(error="Gemini gagal memproses transaksi. Periksa koneksi, API key, dan GEMINI_MODEL."), 502
        if isinstance(exc, (ValueError, KeyError, IndexError, TypeError)):
            app.logger.warning("Could not parse OpenAI response: %s", str(exc)[:300])
            return jsonify(error="Respons AI tidak sesuai format. Coba lagi atau isi secara manual."), 502
        raise


@app.errorhandler(413)
def too_big(_error):
    return jsonify(error=f"Gambar terlalu besar. Maksimal {app.config['MAX_UPLOAD_MB']} MB"), 413


@app.errorhandler(Exception)
def json_api_errors(error):
    if isinstance(error, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error
    app.logger.exception("Unhandled request error")
    if request.path.startswith("/api/"):
        if isinstance(error, RuntimeError):
            return jsonify(error=str(error)), 503
        return jsonify(error="Layanan sedang bermasalah. Periksa konfigurasi Firebase dan coba lagi."), 500
    return "Layanan sedang bermasalah.", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
