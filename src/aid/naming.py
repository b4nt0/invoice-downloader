"""Invoice filename formatting and collision handling."""

from __future__ import annotations

from datetime import date
from pathlib import Path


def format_invoice_name(name_format: str, invoice_date: date) -> str:
    """Apply a ``strftime`` format string to an invoice date."""
    return invoice_date.strftime(name_format)


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
