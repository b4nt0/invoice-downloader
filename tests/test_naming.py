"""Tests for invoice naming helpers."""

import logging
from datetime import date
from pathlib import Path

from aid.naming import (
    format_invoice_name,
    missing_invoice_filename,
    record_missing_invoices,
    unique_path,
    write_missing_invoice,
)


def test_format_invoice_name():
    assert format_invoice_name("%Y-%m-invoice.pdf", date(2026, 4, 15)) == "2026-04-invoice.pdf"


def test_missing_invoice_filename_uses_txt_suffix():
    assert (
        missing_invoice_filename("%Y-%m-invoice.pdf", date(2026, 9, 1))
        == "2026-09-invoice.txt"
    )


def test_write_missing_invoice_records_that_the_invoice_is_missing(tmp_path: Path):
    path = write_missing_invoice(
        tmp_path,
        "%Y-%m-invoice.pdf",
        date(2026, 9, 1),
        "Missing ING Zoomit credit card statement for 2026-09.",
    )
    assert path == tmp_path / "2026-09-invoice.txt"
    assert path.read_text(encoding="utf-8") == (
        "Missing ING Zoomit credit card statement for 2026-09.\n"
    )


def test_record_missing_invoices_logs_and_writes_one_file_per_period(
    tmp_path: Path, caplog
):
    log = logging.getLogger("test.missing")
    with caplog.at_level(logging.ERROR, logger="test.missing"):
        paths = record_missing_invoices(
            [date(2026, 8, 1), date(2026, 9, 1)],
            directory=tmp_path,
            name_format="%Y-%m-invoice.pdf",
            service_label="ING Zoomit credit card statement",
            log=log,
        )

    assert [path.name for path in paths] == [
        "2026-08-invoice.txt",
        "2026-09-invoice.txt",
    ]
    assert paths[1].read_text(encoding="utf-8") == (
        "Missing ING Zoomit credit card statement for 2026-09.\n"
    )
    assert "Missing ING Zoomit credit card statement for 2026-08." in caplog.text
    assert "Missing ING Zoomit credit card statement for 2026-09." in caplog.text


def test_unique_path_no_collision(tmp_path: Path):
    path = unique_path(tmp_path, "2026-04-invoice.pdf")
    assert path == tmp_path / "2026-04-invoice.pdf"


def test_unique_path_with_collisions(tmp_path: Path):
    (tmp_path / "2026-04-invoice.pdf").write_bytes(b"a")
    (tmp_path / "2026-04-invoice-1.pdf").write_bytes(b"b")
    path = unique_path(tmp_path, "2026-04-invoice.pdf")
    assert path == tmp_path / "2026-04-invoice-2.pdf"
