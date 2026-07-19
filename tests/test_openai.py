"""Tests for OpenAI service helpers."""

from __future__ import annotations

from datetime import date

from aid.services.openai import invoice_filename, parse_created_date


def test_parse_created_date():
    assert parse_created_date("25 May 2026, 18:36") == date(2026, 5, 25)
    assert parse_created_date("1 Mar 2026, 15:46") == date(2026, 3, 1)
    assert parse_created_date("27 Dec 2025, 21:59") == date(2025, 12, 27)
    assert parse_created_date("1 Sept 2023, 19:44") == date(2023, 9, 1)
    assert parse_created_date("no date here") is None


def test_invoice_filename_appends_number():
    assert (
        invoice_filename("%Y-%m-invoice.pdf", date(2026, 5, 25), "E300AC26-0024")
        == "2026-05-invoice-E300AC26-0024.pdf"
    )
