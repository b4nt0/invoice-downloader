"""Relative date-range resolution."""

from __future__ import annotations

from datetime import date
from typing import NamedTuple


class DateRange(NamedTuple):
    start: date
    end: date


def last_quarter(today: date | None = None) -> DateRange:
    """Return the latest finished calendar quarter relative to *today*.

    Quarters are inclusive on both ends. For example, on any date in Q3,
    this returns April 1 through June 30 of the same year.
    """
    current = today or date.today()
    year = current.year
    month = current.month

    if month <= 3:
        return DateRange(date(year - 1, 10, 1), date(year - 1, 12, 31))
    if month <= 6:
        return DateRange(date(year, 1, 1), date(year, 3, 31))
    if month <= 9:
        return DateRange(date(year, 4, 1), date(year, 6, 30))
    return DateRange(date(year, 7, 1), date(year, 9, 30))


def resolve_date_range(relative: str, today: date | None = None) -> DateRange:
    """Convert a supported relative date-range name to absolute dates."""
    if relative == "last_quarter":
        return last_quarter(today)
    raise ValueError(f"Unsupported relative date range: {relative}")
