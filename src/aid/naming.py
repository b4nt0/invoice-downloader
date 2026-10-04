"""Invoice filename formatting and collision handling."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


def format_invoice_name(name_format: str, invoice_date: date) -> str:
    """Apply a ``strftime`` format string to an invoice date."""
    return invoice_date.strftime(name_format)


def missing_invoice_filename(name_format: str, invoice_date: date) -> str:
    """Return a ``.txt`` filename that stands in for a missing invoice.

    ``%Y-%m-invoice.pdf`` on 2026-09-01 becomes ``2026-09-invoice.txt``.
    """
    invoice_name = format_invoice_name(name_format, invoice_date)
    return str(Path(invoice_name).with_suffix(".txt"))


def write_missing_invoice(
    directory: Path,
    name_format: str,
    invoice_date: date,
    message: str,
) -> Path:
    """Write *message* to a text file in place of a missing invoice."""
    path = unique_path(directory, missing_invoice_filename(name_format, invoice_date))
    text = message if message.endswith("\n") else f"{message}\n"
    path.write_text(text, encoding="utf-8")
    return path


def record_missing_invoices(
    missing: list[date],
    *,
    directory: Path,
    name_format: str,
    service_label: str,
    log: logging.Logger,
) -> list[Path]:
    """Log each missing period and write a stand-in text file for it.

    Does not raise. Callers keep any invoices already saved and return these
    paths alongside them so the run can continue.
    """
    written: list[Path] = []
    for invoice_date in missing:
        period = invoice_date.strftime("%Y-%m")
        message = f"Missing {service_label} for {period}."
        log.error(message)
        written.append(
            write_missing_invoice(directory, name_format, invoice_date, message)
        )
    return written


def unique_path(directory: Path, filename: str) -> Path:
    """Return a free path under *directory*, appending ``-N`` before the suffix.

    If ``2026-04-invoice.pdf`` exists, the next candidates are
    ``2026-04-invoice-1.pdf``, ``2026-04-invoice-2.pdf``, and so on.
    """
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 1
    while True:
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
