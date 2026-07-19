"""Tests for invoice naming helpers."""

from datetime import date
from pathlib import Path

from aid.naming import format_invoice_name, unique_path


def test_format_invoice_name():
    assert format_invoice_name("%Y-%m-invoice.pdf", date(2026, 4, 15)) == "2026-04-invoice.pdf"


def test_unique_path_no_collision(tmp_path: Path):
    path = unique_path(tmp_path, "2026-04-invoice.pdf")
    assert path == tmp_path / "2026-04-invoice.pdf"


def test_unique_path_with_collisions(tmp_path: Path):
    (tmp_path / "2026-04-invoice.pdf").write_bytes(b"a")
    (tmp_path / "2026-04-invoice-1.pdf").write_bytes(b"b")
    path = unique_path(tmp_path, "2026-04-invoice.pdf")
    assert path == tmp_path / "2026-04-invoice-2.pdf"
