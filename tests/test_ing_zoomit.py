"""Tests for ING Zoomit service helpers."""

from __future__ import annotations

from datetime import date

from aid.services.ing_zoomit import (
    is_credit_card_statement,
    months_in_range,
    parse_month_label,
)


def test_months_in_range():
    assert months_in_range(date(2026, 4, 1), date(2026, 6, 30)) == [
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 6, 1),
    ]


def test_parse_month_label():
    assert parse_month_label("June 2026") == date(2026, 6, 1)
    assert parse_month_label("  May 2026 ") == date(2026, 5, 1)
    assert parse_month_label("Apr 2025") == date(2025, 4, 1)
    assert parse_month_label("no month here") is None


def test_is_credit_card_statement():
    assert is_credit_card_statement(
        "ING\nCredit card expenditure statement\n−647.95"
    )
    assert is_credit_card_statement("CREDIT CARD EXPENDITURE STATEMENT")
    assert not is_credit_card_statement("Bill received on 17/06/2026")
    assert not is_credit_card_statement("EcoWerf\n−43.26")
