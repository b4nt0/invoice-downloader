"""Heroku invoice download automation."""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import Download, Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

INVOICE_ROW = "table tbody tr, [data-testid='invoice-row'], .invoice-row, li"
DOWNLOAD_LINK = "a:has-text('PDF'), a:has-text('Download'), a[href*='invoice']"
MONTH_PATTERN = re.compile(
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def months_in_range(start: date, end: date) -> list[date]:
    """Return the first day of each month overlapping ``[start, end]``."""
    months: list[date] = []
    year, month = start.year, start.month
    while date(year, month, 1) <= end:
        months.append(date(year, month, 1))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def parse_invoice_month(text: str) -> date | None:
    """Parse a Heroku monthly invoice label into the first day of that month."""
    match = MONTH_PATTERN.search(text)
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    return date(int(match.group("year")), month, 1)


def month_overlaps(month_start: date, start: date, end: date) -> bool:
    last_day = monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    return month_start <= end and month_end >= start


class HerokuService:
    """Download monthly invoice PDFs from the Heroku dashboard."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        await page.wait_for_load_state("domcontentloaded")

        try:
            await page.wait_for_selector(INVOICE_ROW, timeout=60_000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Heroku invoices list did not appear; "
                "confirm the account has invoices and the UI still matches selectors"
            ) from exc

        target_months = {
            m for m in months_in_range(start, end) if month_overlaps(m, start, end)
        }
        rows = page.locator(INVOICE_ROW)
        count = await rows.count()
        saved: list[Path] = []
        found_months: set[date] = set()

        for index in range(count):
            row = rows.nth(index)
            text = (await row.inner_text()).strip()
            invoice_month = parse_invoice_month(text)
            if invoice_month is None or invoice_month not in target_months:
                continue
            if invoice_month in found_months:
                continue

            download_control = row.locator(DOWNLOAD_LINK).first
            if await download_control.count() == 0:
                download_control = row.get_by_role("link", name=re.compile("pdf|download", re.I))
            if await download_control.count() == 0:
                raise RuntimeError(
                    f"Heroku invoice row for {invoice_month.strftime('%B %Y')} "
                    "has no download control"
                )

            async with page.expect_download(timeout=120_000) as download_info:
                await download_control.first.click()
            download: Download = await download_info.value

            filename = format_invoice_name(name_format, invoice_month)
            target = unique_path(output_directory, filename)
            await download.save_as(str(target))
            saved.append(target)
            found_months.add(invoice_month)
            logger.info("Saved Heroku invoice %s", target)

        missing = sorted(target_months - found_months)
        if missing:
            labels = ", ".join(m.strftime("%Y-%m") for m in missing)
            raise RuntimeError(f"Missing Heroku invoices for months: {labels}")
        if not saved:
            raise RuntimeError(
                f"No Heroku invoices found in range {start.isoformat()}..{end.isoformat()}"
            )
        return saved
