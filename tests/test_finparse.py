"""Tes offline (tanpa API key): pytest -q"""
from datetime import datetime, timedelta

from finparse import (
    WIB, Category, DateSource, Entry, EntryType, LineItem,
    fingerprint, image_hash, match_expected, parse_dt, validate_entry,
)

NOW = datetime(2026, 10, 12, 13, 5, tzinfo=WIB)


def mk(**kw) -> Entry:
    base = dict(
        type=EntryType.expense, amount_idr=25_000, category=Category.makan_minum,
        occurred_at=None, date_source=DateSource.tidak_ada, merchant=None, account=None,
        note="makan siang", items=[], confidence=0.95,
    )
    base.update(kw)
    return Entry(**base)


def test_clean_entry_has_no_warnings_and_uses_message_time():
    ce = validate_entry(mk(), NOW)
    assert ce.warnings == []
    assert not ce.needs_confirmation
    assert ce.occurred_at == NOW


def test_low_confidence_needs_confirmation():
    ce = validate_entry(mk(confidence=0.5), NOW)
    assert "keyakinan_rendah" in ce.warnings and ce.needs_confirmation


def test_confidence_is_clamped():
    assert validate_entry(mk(confidence=1.7), NOW).entry.confidence == 1.0
    assert validate_entry(mk(confidence=-1), NOW).entry.confidence == 0.0


def test_tiny_amount_flags_missing_thousand_unit():
    assert "nominal_sangat_kecil" in validate_entry(mk(amount_idr=25), NOW).warnings


def test_zero_or_negative_amount_invalid():
    assert "nominal_tidak_valid" in validate_entry(mk(amount_idr=0), NOW).warnings
    assert "nominal_tidak_valid" in validate_entry(mk(amount_idr=-5000), NOW).warnings


def test_large_expense_flagged_but_large_income_is_not():
    assert "nominal_sangat_besar" in validate_entry(mk(amount_idr=12_000_000), NOW).warnings
    gaji = mk(type=EntryType.income, category=Category.gaji, amount_idr=12_000_000)
    assert validate_entry(gaji, NOW).warnings == []


def test_category_not_allowed_for_type_is_fixed():
    ce = validate_entry(mk(type=EntryType.transfer, category=Category.makan_minum), NOW)
    assert ce.entry.category == Category.transfer_internal
    assert "kategori_tidak_cocok_dengan_jenis" in ce.warnings

    ce = validate_entry(mk(type=EntryType.income, category=Category.transport), NOW)
    assert ce.entry.category == Category.pemasukan_lain


def test_items_with_tax_and_service_are_accepted():
    items = [LineItem(name="Nasi", amount_idr=40_000), LineItem(name="Es teh", amount_idr=50_000)]
    ce = validate_entry(mk(amount_idr=99_000, items=items), NOW)  # 90rb + ~10%
    assert "total_tidak_cocok_dengan_item" not in ce.warnings


def test_items_far_from_total_are_flagged():
    items = [LineItem(name="Nasi", amount_idr=40_000)]
    ce = validate_entry(mk(amount_idr=150_000, items=items), NOW)
    assert "total_tidak_cocok_dengan_item" in ce.warnings


def test_future_and_old_dates_flagged():
    future = (NOW + timedelta(days=10)).isoformat()
    old = (NOW - timedelta(days=500)).isoformat()
    assert "tanggal_di_masa_depan" in validate_entry(mk(occurred_at=future), NOW).warnings
    assert "tanggal_terlalu_lama" in validate_entry(mk(occurred_at=old), NOW).warnings


def test_invalid_date_falls_back_to_message_time():
    ce = validate_entry(mk(occurred_at="kemarin"), NOW)
    assert "tanggal_tidak_valid" in ce.warnings
    assert ce.occurred_at == NOW


def test_naive_datetime_is_treated_as_wib():
    dt = parse_dt("2026-10-11T12:00:00")
    assert dt.utcoffset() == timedelta(hours=7) and dt.hour == 12


def test_utc_datetime_is_converted_to_wib():
    assert parse_dt("2026-10-11T05:00:00Z").hour == 12


def test_fingerprint_stable_and_sensitive_to_amount():
    a = validate_entry(mk(merchant="Warteg Bahari"), NOW)
    b = validate_entry(mk(merchant="  warteg bahari "), NOW)
    c = validate_entry(mk(merchant="Warteg Bahari", amount_idr=26_000), NOW)
    assert fingerprint(a) == fingerprint(b) != fingerprint(c)


def test_image_hash_differs_by_content():
    assert image_hash(b"a") != image_hash(b"b")


def test_to_row_shape():
    row = validate_entry(mk(), NOW).to_row("text", recorded_at=NOW)
    assert row["amount_idr"] == 25_000 and row["type"] == "expense" and row["source"] == "text"
    assert row["occurred_at"].endswith("+07:00")


def test_match_expected():
    e = validate_entry(mk(), NOW)
    assert match_expected([e], [{"amount_idr": 25_000, "category": "makan_minum"}])[0]
    assert match_expected([e], [{"category": ["makan_minum", "belanja_harian"]}])[0]
    assert not match_expected([e], [{"amount_idr": 1}])[0]
    assert not match_expected([e], [])[0]
    assert match_expected([], [])[0]
