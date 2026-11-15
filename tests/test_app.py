"""Small backend unit tests that do not require Firebase credentials."""
import app as finance


def test_parse_ai_amount_handles_indonesian_notation():
    assert finance.parse_ai_amount("25rb") == 25_000
    assert finance.parse_ai_amount("8,5jt") == 8_500_000
    assert finance.parse_ai_amount("1.250.000") == 1_250_000
    assert finance.parse_ai_amount(None) is None


def test_account_balance_includes_transfer_direction():
    account = {"id": "cash", "initial_cents": 500_000, "created_at": "2026-01-01T00:00:00"}
    transactions = [
        {"kind": "income", "amount_cents": 100_000, "account_id": "cash", "occurred_at": "2026-01-02T09:00:00"},
        {"kind": "expense", "amount_cents": 25_000, "account_id": "cash", "occurred_at": "2026-01-03T09:00:00"},
        {"kind": "transfer", "amount_cents": 50_000, "account_id": "cash", "destination_id": "bank", "occurred_at": "2026-01-04T09:00:00"},
        {"kind": "transfer", "amount_cents": 20_000, "account_id": "bank", "destination_id": "cash", "occurred_at": "2026-01-05T09:00:00"},
    ]
    assert finance.account_balance(account, transactions) == 545_000
    assert finance.account_balance(account, transactions, before="2026-01-04") == 575_000


from datetime import date, datetime


def test_budget_counts_only_expense_in_category_and_active_month():
    budget = {"id": "b1", "category_id": "food", "allocated_cents": 1_000_000, "created_at": "2026-11-10T00:00:00"}
    transactions = [
        {"id": "1", "kind": "expense", "category_id": "food", "amount_cents": 300_000, "occurred_at": "2026-11-02T12:00:00"},
        {"id": "2", "kind": "expense", "category_id": "food", "amount_cents": 400_000, "occurred_at": "2026-11-14T19:00:00"},
        {"id": "3", "kind": "expense", "category_id": "food", "amount_cents": 999_000, "occurred_at": "2026-10-31T23:59:00"},
        {"id": "4", "kind": "income", "category_id": "food", "amount_cents": 999_000, "occurred_at": "2026-11-05T09:00:00"},
        {"id": "5", "kind": "transfer", "category_id": None, "amount_cents": 999_000, "occurred_at": "2026-11-05T09:00:00"},
        {"id": "6", "kind": "expense", "category_id": "fuel", "amount_cents": 999_000, "occurred_at": "2026-11-05T09:00:00"},
    ]
    view = finance.budget_summary(budget, {"name": "Makan"}, transactions, date(2026, 11, 15))
    # Spending before the budget's created_at still counts: the period is the calendar month.
    assert view["spent_cents"] == 700_000
    assert [item["id"] for item in view["transactions"]] == ["2", "1"]
    assert view["used_percent"] == 70.0
    assert view["status"] == "warning"
    assert view["period"] == "2026-11"
    assert view["period_label"] == "November 2026"
    assert view["days_left"] == 16
    assert view["daily_allowance_cents"] == 300_000 // 16
    assert view["pacing_percent"] == 50.0


def test_budget_status_thresholds_and_overbudget():
    assert finance.budget_status(50, 0) == "safe"
    assert finance.budget_status(50.1, 0) == "warning"
    assert finance.budget_status(75, 0) == "warning"
    assert finance.budget_status(75.1, 0) == "danger"
    assert finance.budget_status(100, 0) == "danger"
    budget = {"category_id": "food", "allocated_cents": 100_000}
    tx = [{"id": "1", "kind": "expense", "category_id": "food", "amount_cents": 125_000, "occurred_at": "2026-11-01T08:00:00"}]
    view = finance.budget_summary(budget, None, tx, date(2026, 11, 30))
    assert view["status"] == "over"
    assert view["bar_percent"] == 100.0
    assert view["overspent_cents"] == 25_000
    assert view["overspent_percent"] == 25.0
    assert view["remaining_cents"] == 0
    assert view["category"] == "Kategori diarsipkan"


def test_wish_stats_use_active_months_since_first_transaction():
    transactions = [
        {"kind": "income", "amount_cents": 6_000_000, "occurred_at": "2026-10-17T09:00:00"},
        {"kind": "expense", "amount_cents": 2_000_000, "occurred_at": "2026-11-01T09:00:00"},
        {"kind": "transfer", "amount_cents": 9_000_000, "occurred_at": "2026-11-02T09:00:00"},
    ]
    stats = finance.wish_savings_stats(transactions, date(2026, 11, 15))
    # 30 days of history -> 1 active month, not a fixed 3-month divisor.
    assert stats["first_transaction_date"] == "2026-10-17"
    assert stats["active_months"] == 1
    assert stats["avg_income_cents"] == 6_000_000
    assert stats["avg_expense_cents"] == 2_000_000
    assert stats["monthly_surplus_cents"] == 4_000_000


def test_wish_stats_cap_window_at_three_months():
    transactions = [
        {"kind": "income", "amount_cents": 9_000_000, "occurred_at": "2026-01-01T09:00:00"},
        {"kind": "income", "amount_cents": 3_000_000, "occurred_at": "2026-10-01T09:00:00"},
        {"kind": "expense", "amount_cents": 6_000_000, "occurred_at": "2026-11-01T09:00:00"},
    ]
    stats = finance.wish_savings_stats(transactions, date(2026, 11, 15))
    assert stats["active_months"] == 3
    assert stats["window_days"] == 90
    assert stats["income_cents"] == 3_000_000
    assert stats["monthly_surplus_cents"] == -1_000_000
    assert finance.wish_savings_stats([], date(2026, 11, 15))["has_data"] is False


def test_wish_view_uses_linked_account_balance_or_manual_allocation():
    accounts = {"pocket": {"id": "pocket", "name": "Tabungan", "active": True}}
    linked = finance.wish_view({"target_cents": 1_000_000, "linked_account_id": "pocket"}, accounts, {"pocket": 250_000})
    assert linked["funding_mode"] == "account"
    assert linked["saved_cents"] == 250_000
    assert linked["progress_percent"] == 25.0
    manual = finance.wish_view({"target_cents": 1_000_000, "manual_saved_cents": 100_000}, accounts, {"pocket": 250_000})
    assert manual["funding_mode"] == "manual"
    assert manual["remaining_cents"] == 900_000
    missing = finance.wish_view({"target_cents": 1_000_000, "linked_account_id": "gone"}, accounts, {})
    assert missing["funding_mode"] == "account_missing"


def test_behavior_counts_days_from_first_transaction_of_year():
    transactions = [
        {"kind": "income", "amount_cents": 5_000_000, "occurred_at": "2026-11-09T08:00:00"},  # Monday
        {"kind": "expense", "amount_cents": 70_000, "occurred_at": "2026-11-14T12:30:00"},  # Saturday
        {"kind": "expense", "amount_cents": 50_000, "occurred_at": "2026-11-10T12:10:00"},  # Tuesday
        {"kind": "transfer", "amount_cents": 1_000_000, "occurred_at": "2026-11-10T21:00:00"},
    ]
    summary = finance.behavior_summary(transactions, date(2026, 11, 15), 2026)
    spending = summary["spending"]
    assert summary["period_start"] == "2026-11-09"
    assert spending["period_days"] == 7
    assert spending["weekday_days"] == 5 and spending["weekend_days"] == 2
    assert spending["daily_average_cents"] == round(120_000 / 7)
    assert spending["weekend_average_cents"] == 35_000
    # Only expenses feed the hour chart.
    assert sum(summary["hour_counts"]) == 2
    assert summary["hour_counts"][12] == 2
    assert summary["hour_totals"][12] == 120_000
    november = summary["months"][10]["days"]
    assert november[13]["weekday"] == 5 and november[13]["expense_count"] == 1
    assert november[0]["tracked"] is False and november[8]["tracked"] is True
    assert november[15]["expense_cents"] is None  # 16 Nov is in the future


def test_behavior_past_year_ends_on_december_31():
    transactions = [{"kind": "expense", "amount_cents": 10_000, "occurred_at": "2025-12-30T10:00:00"}]
    summary = finance.behavior_summary(transactions, date(2026, 11, 15), 2025)
    assert summary["spending"]["period_days"] == 2


def test_unusual_dates_need_confirmation():
    now = datetime(2026, 11, 15, 10, 0)
    assert finance.unusual_date_reason(datetime(2026, 11, 15, 9, 0), now) is None
    assert "2024" in finance.unusual_date_reason(datetime(2024, 11, 15, 9, 0), now)
    assert "masa depan" in finance.unusual_date_reason(datetime(2026, 11, 16, 9, 0), now)
    assert finance.parse_occurred_at("2026-11-15T03:00:00Z", now) == datetime(2026, 11, 15, 10, 0)
    assert finance.parse_occurred_at("", now) == now


def test_new_transactions_counted_after_seen_marker():
    transactions = [
        {"created_at": "2026-11-15T09:00:00"},
        {"created_at": "2026-11-15T10:00:00"},
        {"created_at": "2026-11-15T11:30:00"},
        {},
    ]
    summary = finance.new_transactions_summary(transactions, "2026-11-15T10:00:00")
    assert summary == {"new_transactions_count": 1, "latest_created_at": "2026-11-15T11:30:00"}
    assert finance.new_transactions_summary(transactions, None)["new_transactions_count"] == 0


def test_category_icon_fields_validate_emoji_and_colour():
    assert finance.category_icon_fields({"icon": " 🐱 ", "icon_bg": "#FCE7F3"}) == {"icon": "🐱", "icon_bg": "#fce7f3"}
    assert finance.category_icon_fields({"icon": "👨‍👩‍👧", "icon_bg": "#000000"})["icon"] == "👨‍👩‍👧"
    assert finance.category_icon_fields({"icon": "", "icon_bg": ""}) == {"icon": None, "icon_bg": None}
    assert finance.category_icon_fields({"name": "Makan"}) == {}
    import pytest
    with pytest.raises(ValueError):
        finance.category_icon_fields({"icon": "a b"})
    with pytest.raises(ValueError):
        finance.category_icon_fields({"icon_bg": "red"})


def test_transaction_sequence_numbers_oldest_first():
    transactions = [
        {"id": "c", "occurred_at": "2026-11-10T09:00:00", "created_at": "2026-11-10T09:00:00"},
        {"id": "a", "occurred_at": "2026-01-02T08:00:00", "created_at": "2026-11-15T08:00:00"},  # backdated entry
        {"id": "b", "occurred_at": "2026-11-10T09:00:00", "created_at": "2026-11-10T08:59:00"},
    ]
    assert finance.transaction_sequence(transactions) == {"a": 1, "b": 2, "c": 3}
    rows = finance.transaction_rows(transactions[:1], {}, {}, {"c": 3})
    assert rows[0]["seq"] == 3 and rows[0]["category"] is None


def test_budget_custom_period_counts_only_inside_the_dates():
    budget = {"category_id": "food", "allocated_cents": 100_000, "period_start": "2026-11-10", "period_end": "2026-11-19"}
    tx = [
        {"id": "a", "kind": "expense", "category_id": "food", "amount_cents": 40_000, "occurred_at": "2026-11-09T23:00:00"},
        {"id": "b", "kind": "expense", "category_id": "food", "amount_cents": 60_000, "occurred_at": "2026-11-10T08:00:00"},
        {"id": "c", "kind": "expense", "category_id": "food", "amount_cents": 40_000, "occurred_at": "2026-11-19T21:00:00"},
    ]
    view = finance.budget_summary(budget, {"name": "Makan"}, tx, date(2026, 11, 15))
    assert view["custom_period"] is True
    assert view["spent_cents"] == 100_000
    assert view["exhausted"] is True and view["status"] == "danger"
    assert view["period_label"] == "10 Nov – 19 Nov 2026"
    assert view["days_total"] == 10 and view["days_left"] == 5
    assert view["pacing_percent"] == 60.0
    assert view["period_state"] == "active"


def test_budget_period_states_and_reset():
    budget = {"category_id": "food", "allocated_cents": 100_000, "period_start": "2026-12-01", "period_end": "2026-12-31"}
    assert finance.budget_summary(budget, None, [], date(2026, 11, 15))["period_state"] == "upcoming"
    ended = finance.budget_summary(budget, None, [], date(2027, 1, 5))
    assert ended["period_state"] == "ended" and ended["days_left"] == 0 and ended["exhausted"] is False
    # Reset keeps the length of a custom period, starting today.
    assert finance.next_budget_period(budget, date(2027, 1, 5)) == (date(2027, 1, 5), date(2027, 2, 4))
    # A calendar-month budget resets to one month from today.
    assert finance.next_budget_period({"category_id": "food"}, date(2026, 1, 31)) == (date(2026, 1, 31), date(2026, 2, 28))
    assert finance.one_month_end(date(2026, 11, 15)) == date(2026, 12, 14)
    assert finance.period_label(date(2026, 12, 20), date(2027, 1, 19), True) == "20 Des 2026 – 19 Jan 2027"
