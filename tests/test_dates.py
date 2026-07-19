"""Tests for last_quarter date resolution."""

from datetime import date

from aid.dates import last_quarter, resolve_date_range


def test_last_quarter_in_q3():
    assert last_quarter(date(2026, 7, 19)) == (date(2026, 4, 1), date(2026, 6, 30))


def test_last_quarter_in_q1_crosses_year():
    assert last_quarter(date(2026, 1, 15)) == (date(2025, 10, 1), date(2025, 12, 31))


def test_last_quarter_in_q2():
    assert last_quarter(date(2026, 4, 1)) == (date(2026, 1, 1), date(2026, 3, 31))


def test_last_quarter_in_q4():
    assert last_quarter(date(2026, 11, 30)) == (date(2026, 7, 1), date(2026, 9, 30))


def test_resolve_last_quarter():
    assert resolve_date_range("last_quarter", date(2026, 7, 19)).start == date(2026, 4, 1)
