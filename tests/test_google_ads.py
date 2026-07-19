"""Tests for Google Ads service helpers."""

from __future__ import annotations

from datetime import date

from aid.services.google_ads import (
    is_invoice_document,
    months_in_range,
    parse_document_date,
)


def test_months_in_range():
    assert months_in_range(date(2026, 4, 1), date(2026, 6, 30)) == [
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 6, 1),
    ]


def test_parse_document_date_formats():
    assert parse_document_date("Statement\n30 Jun 2026\n€12.34") == date(2026, 6, 30)
    assert parse_document_date("Invoice June 2026") == date(2026, 6, 1)
    assert parse_document_date("2026-04-15 Invoice") == date(2026, 4, 15)
    assert parse_document_date("Issued 15/04/2026") == date(2026, 4, 15)
    assert parse_document_date("no dates here") is None


def test_is_invoice_document_filters_tax_only_rows():
    assert is_invoice_document("Statement 30 Jun 2026")
    assert is_invoice_document("Invoice 2026-04-01")
    assert is_invoice_document("30 Jun 2026 €10.00")
    assert not is_invoice_document("Tax document 30 Jun 2026")
    assert not is_invoice_document("VAT memo May 2026")
