"""Heroku invoice download automation."""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

# Billing page structure (see docs/specs/heroku/billing-page-sample.html):
# month labels are submit buttons inside tr.invoice-row forms that POST
# into a new tab (target=_blank). There is no PDF download control.
INVOICE_ROW = "div.invoices table tr.invoice-row"
MONTH_BUTTON = "td.invoice-title input[type='submit']"
SHOW_MORE = "div.invoices button.show-more"

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


async def _listed_months(page: Page) -> dict[date, int]:
    """Map visible invoice months to their row index."""
    rows = page.locator(INVOICE_ROW)
    count = await rows.count()
    listed: dict[date, int] = {}
    for index in range(count):
        button = rows.nth(index).locator(MONTH_BUTTON).first
        if await button.count() == 0:
            continue
        label = (await button.get_attribute("value")) or (await button.inner_text())
        invoice_month = parse_invoice_month(label.strip())
        if invoice_month is not None and invoice_month not in listed:
            listed[invoice_month] = index
    return listed


async def _expand_invoice_list(page: Page, target_months: set[date]) -> None:
    """Click 'Show more' until target months are visible or no more history."""
    while True:
        listed = await _listed_months(page)
        if target_months <= listed.keys():
            return
        show_more = page.locator(SHOW_MORE)
        if await show_more.count() == 0 or not await show_more.is_visible():
            return
        previous_count = await page.locator(INVOICE_ROW).count()
        await show_more.click()
        try:
            await page.wait_for_function(
                "(prev) => document.querySelectorAll("
                "'div.invoices table tr.invoice-row'"
                ").length > prev",
                arg=previous_count,
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
            return


async def _print_invoice_page(billing_page: Page, month_button, target: Path) -> None:
    """Open the invoice popup and save it via Chromium print-to-PDF."""
    async with billing_page.expect_popup(timeout=120_000) as popup_info:
        await month_button.click()
    invoice_page = await popup_info.value
    try:
        await invoice_page.wait_for_load_state("domcontentloaded")
        try:
            await invoice_page.wait_for_load_state("networkidle", timeout=60_000)
        except PlaywrightTimeoutError:
            logger.debug("Heroku invoice page did not reach networkidle; printing anyway")
        await invoice_page.pdf(path=str(target), format="Letter", print_background=True)
    finally:
        await invoice_page.close()


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
        await _expand_invoice_list(page, target_months)

        listed = await _listed_months(page)
        saved: list[Path] = []
        found_months: set[date] = set()
        rows = page.locator(INVOICE_ROW)

        for invoice_month in sorted(target_months):
            index = listed.get(invoice_month)
            if index is None:
                continue

            month_button = rows.nth(index).locator(MONTH_BUTTON).first
            if await month_button.count() == 0:
                raise RuntimeError(
                    f"Heroku invoice row for {invoice_month.strftime('%B %Y')} "
                    "has no month link"
                )

            filename = format_invoice_name(name_format, invoice_month)
            target = unique_path(output_directory, filename)
            await _print_invoice_page(page, month_button, target)
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
