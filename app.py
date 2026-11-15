"""My Finance Dashboard: single-owner Flask app backed by Firebase."""
from __future__ import annotations

import base64
import calendar
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
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from flask import Flask, Response, g, has_request_context, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import HTTPException

from config_store import cfg, is_vercel, load_state, save_state
from firebase_store import (
    DEFAULT_PROFILE,
    PROFILE_COLLECTIONS,
    create_record,
    delete_record,
    firestore_client,
    get_record,
    list_records,
    raw_client,
    scoped,
    set_profile_resolver,
    storage_bucket,
    storage_mode,
)

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


def current_profile_id() -> str:
    """The profile whose data this request reads and writes (chosen in the sidebar).

    The session may point at a profile that is not in the current store (e.g. after a
    migration or switching back to local mode); then fall back to the default profile
    instead of silently starting an empty one. Checked once per request.
    """
    if not has_request_context():
        return DEFAULT_PROFILE
    profile_id = str(session.get("profile_id") or DEFAULT_PROFILE)
    if profile_id != DEFAULT_PROFILE and g.get("checked_profile") != profile_id:
        if not raw_client().collection("profiles").document(profile_id).get().exists:
            session["profile_id"] = profile_id = DEFAULT_PROFILE
        g.checked_profile = profile_id
    return profile_id


set_profile_resolver(current_profile_id)


GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DRIVE_INTEGRATION_ID = "google_drive"


def google_drive_configured() -> bool:
    """Client ID, secret and token encryption key set in .env (the redirect URI has a default)."""
    if not (cfg("GOOGLE_DRIVE_CLIENT_ID") and cfg("GOOGLE_DRIVE_CLIENT_SECRET") and cfg("GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY")):
        return False
    try:
        google_drive_cipher()
        return True
    except RuntimeError:
        return False


def google_drive_ready() -> bool:
    """Configured and connected: receipt photos can be uploaded."""
    return google_drive_configured() and bool((google_drive_connection() or {}).get("refresh_token_encrypted"))


def google_drive_redirect_uri() -> str:
    return cfg("GOOGLE_DRIVE_REDIRECT_URI") or url_for("google_drive_callback", _external=True)


def google_drive_cipher():
    from cryptography.fernet import Fernet

    key = cfg("GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY").encode()
    if not key:
        raise RuntimeError("GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY belum diisi di file .env.")
    try:
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError("GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY tidak valid. Gunakan kunci Fernet yang dibuat dengan cryptography.") from exc


def google_drive_connection() -> dict | None:
    return get_record("integrations", GOOGLE_DRIVE_INTEGRATION_ID)


def google_drive_access_token() -> str:
    if not google_drive_configured():
        raise RuntimeError("Google Drive belum diatur. Isi GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, dan GOOGLE_DRIVE_TOKEN_ENCRYPTION_KEY di file .env.")
    connection = google_drive_connection()
    if not connection or not connection.get("refresh_token_encrypted"):
        raise RuntimeError("Hubungkan Google Drive terlebih dahulu.")
    try:
        refresh_token = google_drive_cipher().decrypt(connection["refresh_token_encrypted"].encode()).decode()
    except Exception as exc:
        raise RuntimeError("Token Google Drive tidak dapat dibuka. Hubungkan ulang Google Drive.") from exc
    try:
        response = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": cfg("GOOGLE_DRIVE_CLIENT_ID"),
            "client_secret": cfg("GOOGLE_DRIVE_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError("Tidak dapat terhubung ke Google Drive. Coba lagi sebentar.") from exc
    if not response.ok:
        app.logger.warning("Google Drive token refresh failed with HTTP %s", response.status_code)
        raise RuntimeError("Sesi Google Drive kedaluwarsa atau dicabut. Hubungkan ulang Google Drive.")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Google Drive tidak mengembalikan access token. Hubungkan ulang Google Drive.")
    return token


def google_drive_error(response, operation: str):
    try:
        detail = response.json().get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = ""
    app.logger.warning("Google Drive %s failed with HTTP %s: %s", operation, response.status_code, str(detail)[:250])
    raise RuntimeError("Google Drive gagal memproses foto struk. Periksa koneksi Drive lalu coba lagi.")


def google_drive_receipts_folder(access_token: str) -> str:
    connection = google_drive_connection() or {}
    folder_id = connection.get("receipts_folder_id")
    if folder_id:
        return str(folder_id)
    try:
        response = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": "Bearer " + access_token},
            params={"fields": "id"},
            json={"name": "My Finance Dashboard", "mimeType": "application/vnd.google-apps.folder"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Tidak dapat membuat folder struk di Google Drive.") from exc
    if not response.ok:
        google_drive_error(response, "folder creation")
    folder_id = response.json().get("id")
    if not folder_id:
        raise RuntimeError("Google Drive tidak mengembalikan folder struk.")
    firestore_client().collection("integrations").document(GOOGLE_DRIVE_INTEGRATION_ID).update({"receipts_folder_id": folder_id})
    return folder_id


def upload_google_drive_receipt(filename: str, mime_type: str, image_data: bytes) -> dict:
    access_token = google_drive_access_token()
    folder_id = google_drive_receipts_folder(access_token)
    boundary = "finance-dashboard-" + secrets.token_hex(16)
    metadata = json.dumps({"name": filename, "mimeType": mime_type, "parents": [folder_id]}, ensure_ascii=False).encode("utf-8")
    marker = boundary.encode("ascii")
    body = (
        b"--" + marker + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + metadata + b"\r\n"
        + b"--" + marker + b"\r\nContent-Type: " + mime_type.encode("ascii") + b"\r\n\r\n" + image_data + b"\r\n"
        + b"--" + marker + b"--"
    )
    try:
        response = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            headers={
                "Authorization": "Bearer " + access_token,
                "Content-Type": "multipart/related; boundary=" + boundary,
            },
            params={"uploadType": "multipart", "fields": "id,name,webViewLink,mimeType"},
            data=body,
            timeout=40,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Tidak dapat mengunggah foto ke Google Drive. Coba lagi sebentar.") from exc
    if not response.ok:
        google_drive_error(response, "receipt upload")
    uploaded = response.json()
    file_id = uploaded.get("id")
    if not file_id:
        raise RuntimeError("Google Drive tidak mengembalikan identitas file struk.")
    return {
        "id": file_id,
        "name": uploaded.get("name") or filename,
        "url": uploaded.get("webViewLink") or f"https://drive.google.com/open?id={quote(file_id)}",
    }


def delete_google_drive_file(file_id: str) -> None:
    access_token = google_drive_access_token()
    try:
        response = requests.delete(
            "https://www.googleapis.com/drive/v3/files/" + quote(file_id, safe=""),
            headers={"Authorization": "Bearer " + access_token},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Tidak dapat menghapus foto dari Google Drive.") from exc
    if response.status_code not in (200, 204, 404):
        google_drive_error(response, "receipt deletion")


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


ID_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
# Average month length used to express day spans as months (matches the 90-day = 3-month window).
DAYS_PER_MONTH = 30
WISH_MAX_WINDOW_MONTHS = 3
FUTURE_TOLERANCE = timedelta(minutes=10)
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")


def tx_local_datetime(tx) -> datetime | None:
    """Return occurred_at as a naive Asia/Jakarta datetime, or None when it cannot be parsed."""
    raw = str(tx.get("occurred_at", "") or "").strip()
    if not raw:
        return None
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo:
        timestamp = timestamp.astimezone(JAKARTA).replace(tzinfo=None)
    return timestamp


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def month_label(day: date) -> str:
    return f"{ID_MONTHS[day.month - 1]} {day.year}"


def budget_status(used_percent: float, overspent: int) -> str:
    """Green ≤ 50% used, yellow above 50% up to 75%, red above 75% ("over" = past 100%, still red)."""
    if overspent > 0:
        return "over"
    if used_percent > 75:
        return "danger"
    if used_percent > 50:
        return "warning"
    return "safe"


def parse_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10]) if value else None
    except ValueError:
        return None


def short_date_label(day: date, with_year=True) -> str:
    return f"{day.day} {ID_MONTHS[day.month - 1][:3]}" + (f" {day.year}" if with_year else "")


def budget_period(budget, today: date) -> tuple[date, date, bool]:
    """(start, end, custom). Budgets without their own dates follow the current calendar month."""
    start, end = parse_day(budget.get("period_start")), parse_day(budget.get("period_end"))
    if start and end and start <= end:
        return start, end, True
    month_start, month_end = month_bounds(today)
    return month_start, month_end, False


def period_label(start: date, end: date, custom: bool) -> str:
    if not custom:
        return month_label(start)
    if start.year == end.year:
        return f"{short_date_label(start, with_year=False)} – {short_date_label(end)}"
    return f"{short_date_label(start)} – {short_date_label(end)}"


def next_budget_period(budget, today: date) -> tuple[date, date]:
    """Reset: a fresh period of the same length starting today (a calendar-month budget gets one month)."""
    start, end, custom = budget_period(budget, today)
    if custom:
        return today, today + (end - start)
    return today, one_month_end(today)


def one_month_end(start: date) -> date:
    """Last day of a one-month period: 15 Nov → 14 Dec, 31 Jan → 28 Feb (not 27 Feb)."""
    nxt = shift_month(start, 1)
    return nxt - timedelta(days=1) if nxt.day == start.day else nxt


def shift_month(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def budget_summary(budget, category, transactions, today: date, account_names=None) -> dict:
    """Spending for one budget in its period (expense + category + occurred_at inside the period)."""
    account_names = account_names or {}
    period_start, period_end, custom = budget_period(budget, today)
    total_days = (period_end - period_start).days + 1
    category_id = str(budget.get("category_id", ""))
    spent = 0
    items = []
    for tx in transactions:
        if tx.get("kind") != "expense" or str(tx.get("category_id", "")) != category_id:
            continue
        timestamp = tx_local_datetime(tx)
        if timestamp is None or not period_start <= timestamp.date() <= period_end:
            continue
        amount = int(tx.get("amount_cents", 0) or 0)
        spent += amount
        items.append({
            "id": tx.get("id"),
            "occurred_at": timestamp.isoformat(timespec="seconds"),
            "amount_cents": amount,
            "description": tx.get("description", ""),
            "payment_method": tx.get("payment_method", ""),
            "account": account_names.get(str(tx.get("account_id")), ""),
        })
    items.sort(key=lambda item: (item["occurred_at"], str(item["id"])), reverse=True)
    allocated = int(budget.get("allocated_cents", 0) or 0)
    remaining = max(0, allocated - spent)
    overspent = max(0, spent - allocated)
    used_percent = spent / allocated * 100 if allocated else (100.0 if spent else 0.0)
    if today < period_start:
        period_state, days_left, elapsed = "upcoming", total_days, 0
    elif today > period_end:
        period_state, days_left, elapsed = "ended", 0, total_days
    else:
        period_state, days_left, elapsed = "active", (period_end - today).days + 1, (today - period_start).days + 1
    view = {key: value for key, value in budget.items() if key != "account_id"}
    return view | {
        "category": (category or {}).get("name", "Kategori diarsipkan"),
        "period": period_start.strftime("%Y-%m"),
        "period_label": period_label(period_start, period_end, custom),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "custom_period": custom,
        "period_state": period_state,
        "spent_cents": spent,
        "remaining_cents": remaining,
        "overspent_cents": overspent,
        "used_percent": round(used_percent, 1),
        "bar_percent": round(min(used_percent, 100.0), 1),
        "overspent_percent": round(overspent / allocated * 100, 1) if allocated else 0,
        "status": budget_status(used_percent, overspent),
        # 100% (or more) of the allocation used: the card switches to its "habis" state.
        "exhausted": allocated > 0 and spent >= allocated,
        "days_in_month": total_days,
        "days_total": total_days,
        "days_left": days_left,
        "pacing_percent": round(elapsed / total_days * 100, 1),
        "daily_allowance_cents": remaining // days_left if days_left > 0 else 0,
        "transactions": items,
    }


def wish_savings_stats(transactions, today: date) -> dict:
    """Monthly net cash flow averaged over the active months (first transaction to today, max 3 months)."""
    days = sorted(ts.date() for ts in (tx_local_datetime(tx) for tx in transactions) if ts and ts.date() <= today)
    first_day = days[0] if days else None
    if first_day:
        days_since_first = (today - first_day).days + 1
        window_days = min(days_since_first, WISH_MAX_WINDOW_MONTHS * DAYS_PER_MONTH)
        active_months = min(max(days_since_first / DAYS_PER_MONTH, 1), WISH_MAX_WINDOW_MONTHS)
    else:
        window_days = 0
        active_months = 1
    window_start = today - timedelta(days=max(window_days, 1) - 1)
    income = expense = 0
    for tx in transactions:
        timestamp = tx_local_datetime(tx)
        if not first_day or timestamp is None or not window_start <= timestamp.date() <= today:
            continue
        amount = int(tx.get("amount_cents", 0) or 0)
        if tx.get("kind") == "income":
            income += amount
        elif tx.get("kind") == "expense":
            expense += amount
    avg_income = round(income / active_months)
    avg_expense = round(expense / active_months)
    return {
        "has_data": bool(first_day),
        "first_transaction_date": first_day.isoformat() if first_day else None,
        "window_start": window_start.isoformat() if first_day else None,
        "window_end": today.isoformat(),
        "window_days": window_days,
        "active_months": round(active_months, 2),
        "income_cents": income,
        "expense_cents": expense,
        "avg_income_cents": avg_income,
        "avg_expense_cents": avg_expense,
        "monthly_surplus_cents": avg_income - avg_expense,
    }


def wish_view(wish, accounts_by_id, balances_by_id) -> dict:
    """Attach the saved amount: the linked account balance, or the manual allocation."""
    linked_id = str(wish.get("linked_account_id") or "")
    target = int(wish.get("target_cents", 0) or 0)
    if linked_id:
        account = accounts_by_id.get(linked_id)
        if account and account.get("active", True):
            mode, saved, account_name = "account", max(0, int(balances_by_id.get(linked_id, 0))), account.get("name", "")
        else:
            mode, saved, account_name = "account_missing", 0, (account or {}).get("name", "")
    else:
        mode, saved, account_name = "manual", max(0, int(wish.get("manual_saved_cents", 0) or 0)), ""
    return wish | {
        "funding_mode": mode,
        "linked_account_name": account_name,
        "saved_cents": saved,
        "remaining_cents": max(0, target - saved),
        "progress_percent": round(min(saved / target * 100, 100), 1) if target else 0,
    }


def parse_occurred_at(value, now: datetime) -> datetime:
    """Parse a form/AI timestamp into a naive Asia/Jakarta datetime; empty means now."""
    raw = str(value or "").strip()
    if not raw:
        return now.replace(microsecond=0)
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Tanggal transaksi tidak valid") from exc
    if timestamp.tzinfo:
        timestamp = timestamp.astimezone(JAKARTA).replace(tzinfo=None)
    return timestamp.replace(microsecond=0)


def unusual_date_reason(timestamp: datetime, now: datetime) -> str | None:
    """Explain why a transaction date needs explicit confirmation, or None when it looks normal."""
    label = f"{timestamp.day} {ID_MONTHS[timestamp.month - 1]} {timestamp.year}"
    if timestamp > now + FUTURE_TOLERANCE:
        return f"Tanggal transaksi ({label}) berada di masa depan."
    if timestamp.year != now.year:
        return f"Tahun transaksi ({timestamp.year}) berbeda dari tahun berjalan ({now.year}); tanggal terbaca {label}."
    return None


def transaction_sequence(transactions) -> dict:
    """Friendly running number per transaction: 1 = oldest by transaction date (ties: input time, id)."""
    ordered = sorted(transactions, key=lambda tx: (str(tx.get("occurred_at") or ""), str(tx.get("created_at") or ""), str(tx.get("id", ""))))
    return {str(tx.get("id")): number for number, tx in enumerate(ordered, start=1)}


def transaction_rows(transactions, category_by_id, account_by_id, sequence) -> list[dict]:
    """Attach display names and the running number used by the transaction tables."""
    rows = []
    for tx in transactions:
        category = category_by_id.get(str(tx.get("category_id")), {})
        account = account_by_id.get(str(tx.get("account_id")), {})
        destination = account_by_id.get(str(tx.get("destination_id")), {})
        rows.append(tx | {
            "seq": sequence.get(str(tx.get("id"))),
            "category": category.get("name"),
            "account": account.get("name"),
            "destination": destination.get("name"),
        })
    return rows


UI_SETTINGS_ID = "ui"
HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def new_transactions_summary(transactions, seen_at: str | None) -> dict:
    """Count transactions created after the owner last opened the transaction list."""
    created = [str(tx.get("created_at") or "") for tx in transactions]
    latest = max(created, default="")
    count = sum(1 for value in created if seen_at and value > seen_at)
    return {"new_transactions_count": count, "latest_created_at": latest or None}


def emoji_char_allowed(ch: str) -> bool:
    """Printable, non-space characters plus the invisible parts of composite emoji
    (zero-width joiner in 👨‍👩‍👧 and the tag characters of subdivision flags)."""
    if ch == "‍" or "\U000e0020" <= ch <= "\U000e007f":
        return True
    return ch.isprintable() and not ch.isspace()


def category_icon_fields(data) -> dict:
    """Optional emoji icon + background colour for a category. Empty values reset to the default icon."""
    fields = {}
    if "icon" in data:
        icon = str(data.get("icon") or "").strip()
        if icon and (len(icon) > 16 or not all(emoji_char_allowed(ch) for ch in icon)):
            raise ValueError("Ikon harus berupa satu emoji (tanpa spasi)")
        fields["icon"] = icon or None
    if "icon_bg" in data:
        color = str(data.get("icon_bg") or "").strip()
        if color and not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError("Warna latar ikon harus berformat #RRGGBB")
        fields["icon_bg"] = color.lower() or None
    return fields


def active_accounts_and_transactions():
    # Resolve the active profile's store (and init the Admin client) before the parallel
    # reads: worker threads have no request, so no session and no active profile.
    client = firestore_client()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {collection: pool.submit(list_records, collection, client) for collection in ("accounts", "categories", "transactions", "wishes", "budgets")}
        accounts = futures["accounts"].result()
        categories = futures["categories"].result()
        transactions = futures["transactions"].result()
        wishes = futures["wishes"].result()
        budgets = futures["budgets"].result()
    accounts, categories = ensure_defaults(accounts, categories)
    return accounts, categories, transactions, wishes, budgets


def behavior_summary(transactions, today, selected_year):
    parsed_transactions = []
    available_years = {today.year}
    for tx in transactions:
        timestamp = tx_local_datetime(tx)
        if timestamp is None:
            continue
        parsed_transactions.append((tx, timestamp))
        if timestamp.year <= today.year:
            available_years.add(timestamp.year)

    if selected_year not in available_years:
        selected_year = today.year
    year_start = date(selected_year, 1, 1)
    end_day = min(today, date(selected_year, 12, 31))
    year_transactions = [(tx, ts) for tx, ts in parsed_transactions if year_start <= ts.date() <= end_day]
    # Count days from the first recorded transaction of the year, not from 1 January,
    # so a mid-year start does not dilute the averages with untracked days.
    first_day = min((ts.date() for _, ts in year_transactions), default=None)
    start_day = max(year_start, first_day) if first_day else end_day

    daily_expenses = {}
    daily_counts = {}
    hour_counts = [0] * 24
    hour_totals = [0] * 24
    for tx, timestamp in year_transactions:
        if tx.get("kind") != "expense":
            continue
        amount = int(tx.get("amount_cents", 0) or 0)
        tx_day = timestamp.date()
        hour_counts[timestamp.hour] += 1
        hour_totals[timestamp.hour] += amount
        daily_expenses[tx_day] = daily_expenses.get(tx_day, 0) + amount
        daily_counts[tx_day] = daily_counts.get(tx_day, 0) + 1

    weekday_total = weekend_total = weekday_days = weekend_days = 0
    total_days = (end_day - start_day).days + 1 if first_day else 0
    for offset in range(total_days):
        day = start_day + timedelta(days=offset)
        amount = daily_expenses.get(day, 0)
        if day.weekday() >= 5:
            weekend_total += amount
            weekend_days += 1
        else:
            weekday_total += amount
            weekday_days += 1

    month_cells = []
    for month_number in range(1, 13):
        month_start = date(selected_year, month_number, 1)
        first_weekday = month_start.weekday()
        days = []
        for day_number in range(1, calendar.monthrange(month_start.year, month_start.month)[1] + 1):
            day = date(month_start.year, month_start.month, day_number)
            future = day > end_day
            days.append({
                "day": day_number,
                "date": day.isoformat(),
                # Monday = 0 ... Sunday = 6, matching the calendar rows Sen..Min.
                "weekday": day.weekday(),
                "week": (first_weekday + day_number - 1) // 7,
                "tracked": bool(first_day) and start_day <= day <= end_day,
                "expense_cents": None if future else daily_expenses.get(day, 0),
                "expense_count": None if future else daily_counts.get(day, 0),
            })
        month_cells.append({"key": month_start.strftime("%Y-%m"), "days": days})

    busiest_hour = max(range(24), key=hour_counts.__getitem__) if any(hour_counts) else None
    busiest_amount_hour = max(range(24), key=hour_totals.__getitem__) if any(hour_totals) else None
    total_expense = sum(daily_expenses.values())
    return {
        "year": selected_year,
        "available_years": sorted(available_years, reverse=True),
        "months": month_cells,
        "hour_counts": hour_counts,
        "hour_totals": hour_totals,
        "busiest_hour": busiest_hour,
        "busiest_amount_hour": busiest_amount_hour,
        "has_data": bool(first_day),
        "period_start": start_day.isoformat() if first_day else None,
        "period_end": end_day.isoformat(),
        "spending": {
            "weekday_total_cents": weekday_total,
            "weekend_total_cents": weekend_total,
            "weekday_average_cents": round(weekday_total / weekday_days) if weekday_days else 0,
            "weekend_average_cents": round(weekend_total / weekend_days) if weekend_days else 0,
            "daily_average_cents": round(total_expense / total_days) if total_days else 0,
            "total_cents": total_expense,
            "period_days": total_days,
            "weekday_days": weekday_days,
            "weekend_days": weekend_days,
        },
    }


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
    last = (load_state().get("profiles") or {}).get("last_used")
    if last and (last == DEFAULT_PROFILE or get_record("profiles", last)):
        session["profile_id"] = last
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


@app.get("/auth/google-drive/connect")
@login_required
def connect_google_drive():
    if not google_drive_configured():
        return redirect(url_for("home", drive="not_configured"))
    state = secrets.token_urlsafe(32)
    session["google_drive_oauth_state"] = state
    params = {
        "client_id": cfg("GOOGLE_DRIVE_CLIENT_ID"),
        "redirect_uri": google_drive_redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
        "state": state,
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@app.get("/auth/google-drive/callback")
@login_required
def google_drive_callback():
    expected_state = session.pop("google_drive_oauth_state", "")
    received_state = request.args.get("state", "")
    if not expected_state or not secrets.compare_digest(expected_state, received_state):
        return redirect(url_for("home", drive="state_error"))
    if request.args.get("error"):
        return redirect(url_for("home", drive="denied"))
    code = request.args.get("code", "")
    if not code or not google_drive_configured():
        return redirect(url_for("home", drive="not_configured"))
    try:
        response = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": cfg("GOOGLE_DRIVE_CLIENT_ID"),
            "client_secret": cfg("GOOGLE_DRIVE_CLIENT_SECRET"),
            "redirect_uri": google_drive_redirect_uri(),
            "grant_type": "authorization_code",
        }, timeout=20)
    except requests.RequestException:
        app.logger.warning("Google Drive OAuth code exchange could not reach Google")
        return redirect(url_for("home", drive="connection_error"))
    if not response.ok:
        app.logger.warning("Google Drive OAuth code exchange failed with HTTP %s", response.status_code)
        return redirect(url_for("home", drive="connection_error"))
    tokens = response.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        existing = google_drive_connection() or {}
        if existing.get("refresh_token_encrypted"):
            return redirect(url_for("home", drive="connected"))
        return redirect(url_for("home", drive="token_missing"))
    encrypted = google_drive_cipher().encrypt(refresh_token.encode()).decode()
    firestore_client().collection("integrations").document(GOOGLE_DRIVE_INTEGRATION_ID).set({
        "refresh_token_encrypted": encrypted,
        "receipts_folder_id": (google_drive_connection() or {}).get("receipts_folder_id"),
        "updated_at": stamp_now(),
    })
    return redirect(url_for("home", drive="connected"))


@app.get("/api/google-drive/status")
@login_required
def google_drive_status():
    connection = google_drive_connection() or {}
    return jsonify(configured=google_drive_configured(), connected=bool(connection.get("refresh_token_encrypted")))


@app.post("/api/google-drive/disconnect")
@login_required
def disconnect_google_drive():
    connection = google_drive_connection()
    if connection and connection.get("refresh_token_encrypted"):
        try:
            refresh_token = google_drive_cipher().decrypt(connection["refresh_token_encrypted"].encode()).decode()
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token}, timeout=10)
        except Exception:
            app.logger.warning("Could not revoke the Google Drive refresh token during disconnect", exc_info=True)
    delete_record("integrations", GOOGLE_DRIVE_INTEGRATION_ID)
    return jsonify(ok=True)


@app.get("/api/bootstrap")
@login_required
def bootstrap():
    try:
        accounts, categories, transactions, wishes, budgets = active_accounts_and_transactions()
        today = now_local().date()
        try:
            behavior_year = int(request.args.get("behavior_year", today.year))
        except ValueError:
            return jsonify(error="Tahun Behaviour tidak valid"), 400
        if behavior_year < 1 or behavior_year > today.year:
            return jsonify(error="Tahun Behaviour tidak valid"), 400
        behavior = behavior_summary(transactions, today, behavior_year)
        end = request.args.get("end", today.isoformat())
        start = request.args.get("start", today.replace(day=1).isoformat())
        try:
            client_today = date.fromisoformat(request.args.get("today", today.isoformat()))
        except ValueError:
            client_today = today
        # Trust the browser's calendar date only when it is within a day of the server (time zone skew).
        reference_today = client_today if abs((client_today - today).days) <= 1 else today
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

        account_names = {str(a["id"]): a.get("name", "") for a in accounts}
        active_budgets = [
            budget_summary(budget, category_by_id.get(str(budget.get("category_id", ""))), transactions, reference_today, account_names)
            for budget in budgets
            if budget.get("active", True)
        ]
        active_budgets.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))), reverse=True)

        # The "Rentang" dropdown now only drives the line chart. Cards titled "Bulan Ini",
        # the category breakdown and the recent list always use the current calendar month.
        month_first = reference_today.replace(day=1).isoformat()
        month_today = reference_today.isoformat()
        month_transactions = [tx for tx in transactions if month_first <= str(tx.get("occurred_at", ""))[:10] <= month_today]
        recent = sorted(month_transactions, key=lambda tx: (str(tx.get("occurred_at", "")), str(tx.get("id", ""))), reverse=True)[:500]
        rows = transaction_rows(recent, category_by_id, account_by_id, transaction_sequence(transactions))

        period_transactions = [tx for tx in transactions if start <= str(tx.get("occurred_at", ""))[:10] <= end]
        income = sum(int(tx.get("amount_cents", 0)) for tx in month_transactions if tx.get("kind") == "income")
        expense = sum(int(tx.get("amount_cents", 0)) for tx in month_transactions if tx.get("kind") == "expense")
        bycat = {}
        income_bycat = {}
        for tx in month_transactions:
            if tx.get("kind") in ("expense", "income"):
                totals = bycat if tx.get("kind") == "expense" else income_bycat
                name = category_by_id.get(str(tx.get("category_id")), {}).get("name") or "Lainnya"
                totals[name] = totals.get(name, 0) + int(tx.get("amount_cents", 0))

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

        current_assets = sum(a["balance_cents"] for a in accts)
        wish_stats = wish_savings_stats(transactions, reference_today) | {"current_assets_cents": current_assets}
        balances_by_id = {str(a["id"]): a["balance_cents"] for a in accts}
        wish_rows = [wish_view(wish, account_by_id, balances_by_id) for wish in wishes]
        wish_rows.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))), reverse=True)
        settings = get_record("settings", UI_SETTINGS_ID) or {}
        seen_at = settings.get("transactions_seen_at")
        new_summary = new_transactions_summary(transactions, seen_at)
        if not seen_at:
            # First run: existing history counts as seen; only later entries show as "baru".
            firestore_client().collection("settings").document(UI_SETTINGS_ID).set({"transactions_seen_at": new_summary["latest_created_at"] or stamp_now()}, merge=True)
        features = {
            "ai": ai_config()[2],
            "drive_configured": google_drive_configured(),
            "drive_connected": google_drive_ready(),
            "storage": storage_mode(),
            "vercel": is_vercel(),
        }
        active_profile = next((item for item in profile_list() if item["id"] == current_profile_id()), None)
        return jsonify(**new_summary, features=features, profile=active_profile, accounts=accts, categories=cats, budgets=active_budgets, wishes=wish_rows, wish_stats=wish_stats, behavior=behavior, transactions=rows, csrf=session.get("csrf"), range_start=start, range_end=end, daily=daily, summary={"assets_cents": current_assets, "income_cents": income, "expense_cents": expense, "net_cents": income - expense, "categories": bycat, "income_categories": income_bycat})
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
    accounts, _, transactions, _, _ = active_accounts_and_transactions()
    account = next((item for item in accounts if item["id"] == account_id and item.get("active", True)), None)
    if not account:
        return jsonify(error="Akun tidak ditemukan"), 404
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
    try:
        icon_fields = category_icon_fields(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    categories = list_records("categories")
    active_match = next((c for c in categories if c.get("active", True) and c.get("name", "").casefold() == name.casefold() and c.get("kind") == kind), None)
    if active_match:
        return jsonify(error="Kategori sudah ada"), 409
    archived_match = next((c for c in categories if not c.get("active", True) and c.get("name", "").casefold() == name.casefold() and c.get("kind") == kind), None)
    if archived_match:
        firestore_client().collection("categories").document(archived_match["id"]).update({"name": name, "active": True} | icon_fields)
        return jsonify(ok=True, reactivated=True)
    create_record("categories", {"name": name, "kind": kind, "color": "#8794ff", "active": True} | icon_fields)
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
    if any(item["id"] != category_id and item.get("active", True) and item.get("kind") == category["kind"] and item.get("name", "").casefold() == name.casefold() for item in categories):
        return jsonify(error="Kategori dengan nama tersebut sudah ada"), 409
    try:
        icon_fields = category_icon_fields(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    firestore_client().collection("categories").document(category_id).update({"name": name} | icon_fields)
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
    firestore_client().collection("categories").document(category_id).update({"active": False})
    return jsonify(ok=True)


def wish_fields(data, wish_id=None):
    """Validate wish input. Returns (fields, None) or (None, (message, status))."""
    name = " ".join(str(data.get("name", "")).split())
    if not name or len(name) > 80:
        return None, ("Nama impian wajib diisi (maks. 80 karakter)", 400)
    try:
        target = money(data.get("target"))
    except ValueError as exc:
        return None, (str(exc), 400)
    linked_account_id = str(data.get("linked_account_id") or "").strip()
    fields = {"name": name, "target_cents": target, "linked_account_id": linked_account_id or None}
    if linked_account_id:
        account = get_record("accounts", linked_account_id)
        if not account or not account.get("active", True):
            return None, ("Pilih akun aktif untuk ditautkan ke target", 400)
        # One pocket funds one wish; sharing it would count the same balance twice.
        taken = next((w for w in list_records("wishes") if w["id"] != wish_id and str(w.get("linked_account_id") or "") == linked_account_id), None)
        if taken:
            return None, (f'Akun {account.get("name", "")} sudah ditautkan ke target "{taken.get("name", "")}"', 409)
    elif "saved" in data:
        try:
            fields["manual_saved_cents"] = money(data.get("saved") or 0, allow_zero=True)
        except ValueError as exc:
            return None, (str(exc), 400)
    return fields, None


@app.post("/api/wishes")
@login_required
def create_wish():
    fields, error = wish_fields(request.json or {})
    if error:
        return jsonify(error=error[0]), error[1]
    fields.setdefault("manual_saved_cents", 0)
    create_record("wishes", fields | {"created_at": stamp_now()})
    return jsonify(ok=True)


@app.put("/api/wishes/<wish_id>")
@login_required
def update_wish(wish_id):
    if not get_record("wishes", wish_id):
        return jsonify(error="Impian tidak ditemukan"), 404
    fields, error = wish_fields(request.json or {}, wish_id)
    if error:
        return jsonify(error=error[0]), error[1]
    firestore_client().collection("wishes").document(wish_id).update(fields | {"updated_at": stamp_now()})
    return jsonify(ok=True)


@app.post("/api/wishes/<wish_id>/funds")
@login_required
def add_wish_funds(wish_id):
    wish = get_record("wishes", wish_id)
    if not wish:
        return jsonify(error="Impian tidak ditemukan"), 404
    if wish.get("linked_account_id"):
        return jsonify(error="Target ini mengikuti saldo akun yang ditautkan. Tambah dana dengan mencatat transfer ke akun tersebut."), 409
    try:
        amount = money((request.json or {}).get("amount"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    from google.cloud.firestore import Increment

    firestore_client().collection("wishes").document(wish_id).update({"manual_saved_cents": Increment(amount), "updated_at": stamp_now()})
    return jsonify(ok=True)


@app.delete("/api/wishes/<wish_id>")
@login_required
def delete_wish(wish_id):
    if not get_record("wishes", wish_id):
        return jsonify(error="Impian tidak ditemukan"), 404
    delete_record("wishes", wish_id)
    return jsonify(ok=True)


def budget_fields(data, budget_id=None):
    """Validate budget input. Returns (fields, None) or (None, (message, status))."""
    name = " ".join(str(data.get("name", "")).split())
    category_id = str(data.get("category_id", ""))
    if not name or len(name) > 80:
        return None, ("Nama budget wajib diisi (maks. 80 karakter)", 400)
    try:
        allocated = money(data.get("amount"))
    except ValueError as exc:
        return None, (str(exc), 400)
    category = get_record("categories", category_id)
    if not category or not category.get("active", True) or category.get("kind") != "expense":
        return None, ("Pilih kategori pengeluaran yang aktif", 400)
    if any(item["id"] != budget_id and item.get("active", True) and str(item.get("category_id")) == category_id for item in list_records("budgets")):
        return None, ("Kategori ini sudah terhubung ke budget lain", 409)
    raw_start, raw_end = str(data.get("period_start") or "").strip(), str(data.get("period_end") or "").strip()
    if bool(raw_start) != bool(raw_end):
        return None, ("Isi tanggal mulai dan tanggal selesai periode, atau kosongkan keduanya", 400)
    period_start = period_end = None
    if raw_start:
        start, end = parse_day(raw_start), parse_day(raw_end)
        if not start or not end:
            return None, ("Tanggal periode tidak valid", 400)
        if end < start:
            return None, ("Tanggal selesai harus sama atau setelah tanggal mulai", 400)
        if (end - start).days > 366:
            return None, ("Periode budget maksimal 1 tahun", 400)
        period_start, period_end = start.isoformat(), end.isoformat()
    # Empty dates = follow the calendar month (the original, repeating behaviour).
    return {"name": name, "category_id": category_id, "allocated_cents": allocated, "period_start": period_start, "period_end": period_end}, None


@app.post("/api/budgets")
@login_required
def create_budget():
    fields, error = budget_fields(request.json or {})
    if error:
        return jsonify(error=error[0]), error[1]
    create_record("budgets", fields | {"active": True, "created_at": stamp_now()})
    return jsonify(ok=True)


@app.put("/api/budgets/<budget_id>")
@login_required
def update_budget(budget_id):
    budget = get_record("budgets", budget_id)
    if not budget or not budget.get("active", True):
        return jsonify(error="Budget tidak ditemukan"), 404
    fields, error = budget_fields(request.json or {}, budget_id)
    if error:
        return jsonify(error=error[0]), error[1]
    firestore_client().collection("budgets").document(budget_id).update(fields | {"updated_at": stamp_now()})
    return jsonify(ok=True)


@app.post("/api/budgets/<budget_id>/reset")
@login_required
def reset_budget(budget_id):
    """Start a fresh period from today with the same allocation; earlier spending no longer counts."""
    budget = get_record("budgets", budget_id)
    if not budget or not budget.get("active", True):
        return jsonify(error="Budget tidak ditemukan"), 404
    start, end = next_budget_period(budget, now_local().date())
    firestore_client().collection("budgets").document(budget_id).update({
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "reset_at": stamp_now(),
        "updated_at": stamp_now(),
    })
    return jsonify(ok=True, period_start=start.isoformat(), period_end=end.isoformat())


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
    data = request.form if request.mimetype == "multipart/form-data" else (request.json or {})
    kind = data.get("kind")
    account_id = str(data.get("account_id", ""))
    destination_id = str(data.get("destination_id", ""))
    receipt_file = str(data.get("receipt_file", "")).strip()
    receipt_upload = request.files.get("receipt") if request.files else None
    receipt_bytes = None
    receipt_name = None
    if receipt_upload and receipt_upload.filename:
        if receipt_upload.mimetype not in ("image/jpeg", "image/png", "image/webp"):
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        receipt_bytes = receipt_upload.read()
        if len(receipt_bytes) > app.config["MAX_UPLOAD_BYTES"]:
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        receipt_name = os.path.basename(receipt_upload.filename.replace("\\", "/"))
        receipt_name = "".join(char for char in receipt_name if char.isprintable()).strip()[:120] or "struk"
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
    now = now_local()
    try:
        occurred = parse_occurred_at(data.get("occurred_at"), now)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    date_warning = unusual_date_reason(occurred, now)
    if date_warning and str(data.get("confirm_unusual_date", "")).lower() not in ("1", "true"):
        return jsonify(error=date_warning + " Konfirmasi untuk tetap menyimpan.", date_warning=date_warning, needs_date_confirmation=True), 409
    # The form sends one random request_id per entry; it becomes the document ID, so a
    # repeated submit (double click, retry after a lost response) cannot create a duplicate.
    request_id = str(data.get("request_id", "")).strip()
    if request_id and not REQUEST_ID_PATTERN.fullmatch(request_id):
        return jsonify(error="ID permintaan tidak valid. Muat ulang halaman lalu coba lagi."), 400
    if request_id and get_record("transactions", request_id):
        return jsonify(ok=True, duplicate=True)
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
    drive_receipt = None
    if receipt_file:
        bucket = storage_bucket()
        draft_blob = bucket.blob("draft-receipts/" + receipt_file)
        if not draft_blob.exists():
            return jsonify(error="Foto struk tidak ditemukan. Unggah ulang struk sebelum menyimpan."), 400
        saved_blob = bucket.blob("receipts/" + receipt_file)
        bucket.copy_blob(draft_blob, bucket, new_name=saved_blob.name)
        draft_blob.delete()
    warnings = []
    if receipt_bytes is not None:
        if not google_drive_ready():
            # Drive is optional: keep the transaction, tell the user the photo was not stored.
            warnings.append("Transaksi tersimpan, tetapi foto struk tidak disimpan karena Google Drive belum diatur atau belum terhubung.")
        else:
            try:
                drive_receipt = upload_google_drive_receipt(receipt_name, receipt_upload.mimetype, receipt_bytes)
            except RuntimeError as exc:
                return jsonify(error=str(exc)), 503
    occurred_at = occurred.isoformat(timespec="seconds")
    description = " ".join(str(data.get("description", "")).split())[:300]
    record = {"kind": kind, "amount_cents": cents, "category_id": category_id, "account_id": account_id, "destination_id": destination_id if kind == "transfer" else None, "description": description, "payment_method": str(data.get("payment_method", ""))[:50], "original_input": str(data.get("original_input", ""))[:1000], "occurred_at": occurred_at, "created_at": stamp_now(), "receipt_file": receipt_file or None, "receipt_drive_id": drive_receipt["id"] if drive_receipt else None, "receipt_drive_url": drive_receipt["url"] if drive_receipt else None, "receipt_name": drive_receipt["name"] if drive_receipt else None}

    def discard_uploads(include_blob=True):
        # A duplicate request shares the legacy blob name with the first record, so keep it then.
        if include_blob and saved_blob and saved_blob.exists():
            saved_blob.delete()
        if drive_receipt:
            try:
                delete_google_drive_file(drive_receipt["id"])
            except RuntimeError:
                app.logger.warning("Failed to remove unlinked Google Drive receipt after transaction save failed")

    try:
        if request_id:
            from google.api_core.exceptions import Conflict

            try:
                # create() fails if the document exists, unlike set(), which would overwrite it.
                firestore_client().collection("transactions").document(request_id).create(record)
            except Conflict:
                discard_uploads(include_blob=False)
                return jsonify(ok=True, duplicate=True)
        else:
            create_record("transactions", record)
    except Exception:
        discard_uploads()
        raise
    return jsonify(ok=True, warnings=warnings)


@app.get("/api/transactions/history")
@login_required
def transaction_history():
    """Every transaction (newest first) for the Transaksi tab, independent of the dashboard range."""
    firestore_client()
    client = firestore_client()  # active profile, resolved before entering worker threads
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(list_records, name, client) for name in ("accounts", "categories", "transactions")}
        accounts, categories, transactions = (futures[name].result() for name in ("accounts", "categories", "transactions"))
    category_by_id = {str(c["id"]): c for c in categories}
    account_by_id = {str(a["id"]): a for a in accounts}
    ordered = sorted(transactions, key=lambda tx: (str(tx.get("occurred_at", "")), str(tx.get("created_at", "")), str(tx.get("id", ""))), reverse=True)
    return jsonify(transactions=transaction_rows(ordered, category_by_id, account_by_id, transaction_sequence(transactions)))


@app.post("/api/transactions/seen")
@login_required
def mark_transactions_seen():
    """Remember that the owner has looked at every transaction created up to seen_at."""
    raw = str((request.json or {}).get("seen_at") or "").strip()
    try:
        datetime.fromisoformat(raw)
    except ValueError:
        return jsonify(error="Penanda waktu tidak valid"), 400
    # Never move the marker backwards or into the future.
    seen_at = min(raw, stamp_now())
    ref = firestore_client().collection("settings").document(UI_SETTINGS_ID)
    current = (get_record("settings", UI_SETTINGS_ID) or {}).get("transactions_seen_at") or ""
    if seen_at > current:
        ref.set({"transactions_seen_at": seen_at}, merge=True)
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
    if "destination_id" in data:
        if tx.get("kind") != "transfer":
            return jsonify(error="Hanya transaksi transfer yang memiliki akun tujuan"), 400
        destination_id = str(data.get("destination_id", ""))
        destination = get_record("accounts", destination_id)
        if not destination or not destination.get("active", True):
            return jsonify(error="Pilih akun tujuan yang aktif"), 400
        if destination_id == str(updates.get("account_id", tx.get("account_id"))):
            return jsonify(error="Akun tujuan tidak boleh sama dengan akun sumber"), 400
        updates["destination_id"] = destination_id
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
    if tx.get("receipt_drive_id"):
        try:
            delete_google_drive_file(str(tx["receipt_drive_id"]))
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 503
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


def ai_config() -> tuple[str, str, bool]:
    """(provider, api_key, enabled). Enabled when a key exists, unless AI_ENABLED=false."""
    provider = cfg("AI_PROVIDER", "gemini").strip().lower()
    key = cfg("GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY")
    disabled = cfg("AI_ENABLED", "true").strip().lower() == "false"
    return provider, key, bool(key) and not disabled and provider in ("gemini", "openai")


@app.post("/api/parse")
@login_required
def parse_ai():
    provider, api_key, enabled = ai_config()
    if provider not in ("gemini", "openai"):
        return jsonify(error="AI_PROVIDER di file .env harus gemini atau openai."), 503
    if not api_key:
        return jsonify(error="AI belum diatur. Isi GEMINI_API_KEY (atau OPENAI_API_KEY) di file .env, lalu jalankan ulang aplikasi.", needs_setup="ai"), 503
    if not enabled:
        return jsonify(error="AI dinonaktifkan oleh AI_ENABLED=false di environment.", needs_setup="ai"), 503
    data = request.form if request.mimetype == "multipart/form-data" else (request.json or {})
    text = str(data.get("text", ""))[:3000]
    image = request.files.get("receipt") if request.files else None
    image_data = None
    image_mime = None
    image_filename = None
    categories = [item for item in list_records("categories") if item.get("active", True)]
    accounts = [item for item in list_records("accounts") if item.get("active", True)]
    budgets = list_records("budgets")
    category_guide = "\nKategori aktif (gunakan nama dan jenis persis dari daftar ini): " + json.dumps([{"name": item["name"], "kind": item["kind"]} for item in categories], ensure_ascii=False)
    category_by_id = {str(item["id"]): item for item in categories}
    budget_guide = "\nBudget aktif dan kategori penghubungnya (bila deskripsi jelas merujuk budget, pilih kategori penghubungnya): " + json.dumps([{"name": item.get("name", ""), "category": category_by_id.get(str(item.get("category_id", "")), {}).get("name", "")} for item in budgets if item.get("active", True)], ensure_ascii=False)
    account_names = [item["name"] for item in accounts]
    account_guide = "\nAkun aktif yang tersedia: " + json.dumps(account_names, ensure_ascii=False)
    user_text = "Ekstrak satu transaksi ke JSON untuk draft; jangan mengarang. Field: type (income|expense|transfer), amount (nominal rupiah integer, gunakan 0 jika tidak diketahui), category (nama kategori tersedia atau Transfer), account (nama akun aktif yang membayar/menerima, atau string kosong), destination_account (akun tujuan transfer, atau string kosong), description, payment_method (metode seperti QRIS, tunai, debit; string kosong jika tidak disebut), occurred_at (ISO atau string kosong bila tanggal tidak disebut), confidence (0-1), question (string kosong atau pertanyaan klarifikasi). Bedakan nama metode pembayaran dari nama akun. Jika input menyebut 'QRIS Mandiri', isi payment_method='QRIS' dan account='Mandiri' bila Mandiri ada di daftar akun. Pilih kategori custom paling cocok secara makna dari daftar, jangan membuat kategori baru. Jangan menebak akun atau metode yang tidak disebut. Perpindahan dana antar akun milik sendiri, termasuk penggantian talangan/reimburse (misalnya talangan tunai yang diganti lewat transfer bank), dicatat sebagai type transfer dengan account sumber dan destination_account tujuan, bukan sebagai income dan expense terpisah; jelaskan konteksnya di description." + f"\nHari ini: {now_local().date().isoformat()} (zona Asia/Jakarta). Tulis tahun lengkap empat digit pada occurred_at. Bila struk menulis tahun dua digit (misal 15/11/26), artikan sebagai 20xx. Jangan menebak tahun yang tidak tertulis." + category_guide + budget_guide + account_guide + ("\nInput: " + text if text else "\nBaca struk berikut.")
    if image and image.filename:
        if image.mimetype not in ("image/jpeg", "image/png", "image/webp"):
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        image_data = image.read()
        if len(image_data) > app.config["MAX_UPLOAD_BYTES"]:
            return jsonify(error=f"Gambar harus JPG, PNG, WebP dan maksimal {app.config['MAX_UPLOAD_MB']} MB"), 400
        image_mime = image.mimetype
        image_filename = os.path.basename(image.filename.replace("\\", "/"))
        image_filename = "".join(char for char in image_filename if char.isprintable()).strip()[:120] or "struk"
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
            response = client.models.generate_content(model=cfg("GEMINI_MODEL", "gemini-3.8-flash"), contents=contents, config=types.GenerateContentConfig(system_instruction=prompt, response_mime_type="application/json", response_schema=schema, temperature=0.1))
            result = json.loads(response.text or "")
        else:
            content = [{"type": "text", "text": user_text}]
            if image_data:
                payload = base64.b64encode(image_data).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{payload}"}})
            response = requests.post(cfg("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + api_key}, json={"model": cfg("OPENAI_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": prompt + " Jawab JSON valid saja."}, {"role": "user", "content": content}]}, timeout=35)
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
        result["date_warning"] = None
        if str(result.get("occurred_at") or "").strip():
            now = now_local()
            try:
                parsed_at = parse_occurred_at(result["occurred_at"], now)
                result["occurred_at"] = parsed_at.isoformat(timespec="seconds")
                result["date_warning"] = unusual_date_reason(parsed_at, now)
            except ValueError:
                result["occurred_at"] = ""
                result["date_warning"] = "Tanggal pada input tidak terbaca; waktu saat ini dipakai. Periksa kembali tanggalnya."
        result["question"] = result.get("question") or ("Nominal belum terbaca. Mohon lengkapi sebelum menyimpan." if not result["amount"] else None)
        result["needs_confirmation"] = True
        if image_data:
            result["receipt_name"] = image_filename
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


PROFILE_NAME_MAX = 40


def profile_list() -> list[dict]:
    """All profiles, the default one first. The default profile exists even without a doc."""
    docs = {item["id"]: item for item in list_records("profiles")}
    default = docs.pop(DEFAULT_PROFILE, {})
    profiles = [{"id": DEFAULT_PROFILE, "name": default.get("name") or "Profil utama", "created_at": default.get("created_at", "")}]
    profiles += sorted(({"id": pid, "name": d.get("name") or "Profil", "created_at": d.get("created_at", "")}
                        for pid, d in docs.items()), key=lambda item: (item["created_at"], item["id"]))
    return profiles


def profiles_payload() -> dict:
    profiles = profile_list()
    active = current_profile_id()
    if active not in {item["id"] for item in profiles}:
        active = DEFAULT_PROFILE
        session["profile_id"] = DEFAULT_PROFILE
    return {"active": active, "profiles": profiles}


def profile_fields(data) -> tuple[dict | None, str | None]:
    name = " ".join(str(data.get("name") or "").split())
    if not name or len(name) > PROFILE_NAME_MAX:
        return None, f"Nama profil wajib diisi (maks. {PROFILE_NAME_MAX} karakter)"
    return {"name": name}, None


@app.get("/api/profiles")
@login_required
def get_profiles():
    return jsonify(profiles_payload())


@app.post("/api/profiles")
@login_required
def create_profile():
    """New profile with empty data (default accounts/categories appear on first load); switch to it."""
    fields, error = profile_fields(request.json or {})
    if error:
        return jsonify(error=error), 400
    if any(item["name"].casefold() == fields["name"].casefold() for item in profile_list()):
        return jsonify(error="Sudah ada profil dengan nama itu"), 409
    profile_id = create_record("profiles", fields | {"created_at": stamp_now()})
    session["profile_id"] = profile_id
    save_state("profiles", {"last_used": profile_id})
    return jsonify(profiles_payload())


@app.put("/api/profiles/<profile_id>")
@login_required
def update_profile(profile_id):
    fields, error = profile_fields(request.json or {})
    if error:
        return jsonify(error=error), 400
    known = {item["id"]: item for item in profile_list()}
    if profile_id not in known:
        return jsonify(error="Profil tidak ditemukan"), 404
    if any(pid != profile_id and item["name"].casefold() == fields["name"].casefold() for pid, item in known.items()):
        return jsonify(error="Sudah ada profil dengan nama itu"), 409
    raw_client().collection("profiles").document(profile_id).set(fields | {"updated_at": stamp_now()}, merge=True)
    return jsonify(profiles_payload())


PROFILE_SUMMARY = (("transactions", "transaksi"), ("accounts", "akun"), ("budgets", "budget"), ("wishes", "wish"))


@app.get("/api/profiles/<profile_id>/summary")
@login_required
def profile_summary(profile_id):
    """How much data a profile holds, shown before deleting it."""
    if profile_id not in {item["id"] for item in profile_list()}:
        return jsonify(error="Profil tidak ditemukan"), 404
    client = scoped(raw_client(), profile_id)
    return jsonify(counts={name: sum(1 for _ in client.collection(name).stream()) for name, _label in PROFILE_SUMMARY})


@app.delete("/api/profiles/<profile_id>")
@login_required
def delete_profile(profile_id):
    """Delete a profile and all of its data. The default profile cannot be deleted."""
    if profile_id == DEFAULT_PROFILE:
        return jsonify(error="Profil utama tidak bisa dihapus"), 400
    if profile_id not in {item["id"] for item in profile_list()}:
        return jsonify(error="Profil tidak ditemukan"), 404
    raw = raw_client()
    client = scoped(raw, profile_id)
    refs = [client.collection(name).document(doc.id) for name in sorted(PROFILE_COLLECTIONS) for doc in client.collection(name).stream()]
    refs.append(raw.collection("profiles").document(profile_id))  # last, so a partial failure can be retried
    for start in range(0, len(refs), 400):  # Firestore batches hold at most 500 writes
        batch = raw.batch()
        for ref in refs[start:start + 400]:
            batch.delete(ref)
        batch.commit()
    if session.get("profile_id") == profile_id:
        session["profile_id"] = DEFAULT_PROFILE
    g.pop("checked_profile", None)
    if (load_state().get("profiles") or {}).get("last_used") == profile_id:
        save_state("profiles", {"last_used": DEFAULT_PROFILE})
    return jsonify(profiles_payload())


@app.post("/api/profiles/<profile_id>/switch")
@login_required
def switch_profile(profile_id):
    if profile_id not in {item["id"] for item in profile_list()}:
        return jsonify(error="Profil tidak ditemukan"), 404
    session["profile_id"] = profile_id
    save_state("profiles", {"last_used": profile_id})
    return jsonify(profiles_payload())


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
