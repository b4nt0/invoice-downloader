"""Google Ads invoice download automation."""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import FrameLocator, Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, record_missing_invoices, unique_path

logger = logging.getLogger(__name__)

# Documents page structure (see docs/specs/google-ads/ads-page.html):
# invoices live in a Google Payments document-center iframe. Each data row
# has an <a class="b3id-button-link" role="button">Download</a> control.
DOCUMENTS_VIEW = "documents-view"
DOCUMENTS_IFRAME = "#post-signup-embedded-page-containerIframe"
DOWNLOAD_BUTTON = "a.b3id-button-link:text-is('Download')"
DOCUMENT_ROW = "tr.b3id-widget-table-data-row"

# Prefer billing statements/invoices over tax memos when the row labels them.
INVOICE_TYPE_PATTERN = re.compile(r"\b(?:invoice|statement)\b", re.IGNORECASE)
TAX_TYPE_PATTERN = re.compile(r"\b(?:tax|vat)\b", re.IGNORECASE)

DATE_PATTERNS = (
    # 30 Jun 2026 / 30 June 2026
    re.compile(
        r"(?P<day>\d{1,2})\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    # Jun 2026 / June 2026
    re.compile(
        r"(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    # 2026-06-30
    re.compile(r"(?P<year>\d{4})-(?P<month_num>\d{1,2})-(?P<day>\d{1,2})"),
    # 30/06/2026 (en_GB)
    re.compile(r"(?P<day>\d{1,2})/(?P<month_num>\d{1,2})/(?P<year>\d{4})"),
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


def month_overlaps(month_start: date, start: date, end: date) -> bool:
    last_day = monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    return month_start <= end and month_end >= start


def parse_document_date(text: str) -> date | None:
    """Parse a document issue/period date from row text into a calendar date."""
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        year = int(groups["year"])
        if "month" in groups and groups["month"]:
            month = MONTHS[groups["month"].lower()]
        else:
            month = int(groups["month_num"])
        day = int(groups["day"]) if groups.get("day") else 1
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def is_invoice_document(text: str) -> bool:
    """Return True when the row looks like an invoice/statement, not a tax memo."""
    if TAX_TYPE_PATTERN.search(text) and not INVOICE_TYPE_PATTERN.search(text):
        return False
    if INVOICE_TYPE_PATTERN.search(text):
        return True
    # Rows without an explicit type still count (some tables only show dates).
    return True


async def _documents_frame(page: Page) -> FrameLocator:
    """Wait for the Payments document-center iframe and return a frame locator."""
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(DOCUMENTS_VIEW, timeout=60_000)
    except PlaywrightTimeoutError:
        logger.debug("documents-view not found; waiting for iframe directly")

    try:
        await page.wait_for_selector(DOCUMENTS_IFRAME, timeout=60_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Google Ads documents iframe did not appear; "
            "confirm Billing → Documents is reachable and the UI still matches"
        ) from exc

    frame = page.frame_locator(DOCUMENTS_IFRAME)
    try:
        await frame.locator(DOWNLOAD_BUTTON).first.wait_for(
            state="visible", timeout=60_000
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Google Ads document Download links did not appear inside the "
            "Payments iframe; confirm the account has documents and the UI "
            "still matches selectors"
        ) from exc
    return frame


async def _row_text_for_download(button) -> str:
    """Return the surrounding table-row text for a Download control."""
    text = await button.evaluate(
        """(el) => {
            const host =
                el.closest('tr.b3id-widget-table-data-row, tr, [role="row"]') ||
                el.parentElement;
            return host ? host.innerText : (el.textContent || '');
        }"""
    )
    return (text or "").strip()


async def _listed_documents(frame: FrameLocator) -> list[tuple[date, int]]:
    """Map visible invoice/statement rows to (month_start, download_index)."""
    buttons = frame.locator(DOWNLOAD_BUTTON)
    count = await buttons.count()
    listed: list[tuple[date, int]] = []

    for index in range(count):
        text = await _row_text_for_download(buttons.nth(index))
        if not text or not is_invoice_document(text):
            continue

        document_date = parse_document_date(text)
        if document_date is None:
            logger.debug("Skipping Google Ads document without parseable date: %r", text)
            continue

        month_start = date(document_date.year, document_date.month, 1)
        listed.append((month_start, index))

    return listed


async def _download_document(
    page: Page,
    frame: FrameLocator,
    button_index: int,
    target: Path,
) -> None:
    """Click a row Download control and save the resulting PDF."""
    button = frame.locator(DOWNLOAD_BUTTON).nth(button_index)
    async with page.expect_download(timeout=120_000) as download_info:
        await button.click()
    download = await download_info.value
    await download.save_as(str(target))


class GoogleAdsService:
    """Download monthly invoice PDFs from the Google Ads Documents page."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        frame = await _documents_frame(page)

        target_months = {
            m for m in months_in_range(start, end) if month_overlaps(m, start, end)
        }
        listed = await _listed_documents(frame)

        # One download per month: prefer the first matching document for that month.
        by_month: dict[date, int] = {}
        for month_start, index in listed:
            if month_start in target_months and month_start not in by_month:
                by_month[month_start] = index

        saved: list[Path] = []
        found_months: set[date] = set()

        for month_start in sorted(target_months):
            index = by_month.get(month_start)
            if index is None:
                continue

            filename = format_invoice_name(name_format, month_start)
            target = unique_path(output_directory, filename)
            await _download_document(page, frame, index, target)
            saved.append(target)
            found_months.add(month_start)
            logger.info("Saved Google Ads invoice %s", target)

        missing = sorted(target_months - found_months)
        saved.extend(
            record_missing_invoices(
                missing,
                directory=output_directory,
                name_format=name_format,
                service_label="Google Ads invoice",
                log=logger,
            )
        )
        if not saved:
            raise RuntimeError(
                f"No Google Ads invoices found in range "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        return saved
