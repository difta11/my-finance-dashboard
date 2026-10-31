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
