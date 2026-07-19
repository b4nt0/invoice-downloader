"""OpenAI Platform billing invoice download automation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name

logger = logging.getLogger(__name__)

# Billing history page (see docs/specs/openai/openai.html):
# invoices are rows in table.billing-history-table; each has a View link that
# opens a Stripe hosted-invoice page (see openai-view.html) where
# "Download invoice" saves the PDF.
HISTORY_TABLE = "table.billing-history-table"
INVOICE_ROW = f"{HISTORY_TABLE} tbody tr"
VIEW_LINK = "a:has-text('View')"
DOWNLOAD_INVOICE_BUTTON = "button:has-text('Download invoice')"

CREATED_PATTERN = re.compile(
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|"
    r"Oct|Nov|Dec)"
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
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


@dataclass(frozen=True)
class OpenAIInvoice:
    """One billing-history row in the configured date range."""

    number: str
    created: date
    row_index: int


def parse_created_date(text: str) -> date | None:
    """Parse an OpenAI Created cell like ``25 May 2026, 18:36``."""
    match = CREATED_PATTERN.search(text)
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def invoice_filename(name_format: str, invoice_date: date, invoice_number: str) -> str:
    """Apply the download format and append the invoice number before the suffix.

    ``%Y-%m-invoice.pdf`` + ``E300AC26-0024`` → ``2026-05-invoice-E300AC26-0024.pdf``.
    """
    base = format_invoice_name(name_format, invoice_date)
    path = Path(base)
    return f"{path.stem}-{invoice_number}{path.suffix}"


async def _listed_invoices(page: Page, start: date, end: date) -> list[OpenAIInvoice]:
    """Collect billing-history rows whose Created date falls in ``[start, end]``."""
    rows = page.locator(INVOICE_ROW)
    count = await rows.count()
    listed: list[OpenAIInvoice] = []

    for index in range(count):
        row = rows.nth(index)
        cells = row.locator("td")
        if await cells.count() < 4:
            continue

        number = (await cells.nth(0).inner_text()).strip()
        created_text = (await cells.nth(3).inner_text()).strip()
        created = parse_created_date(created_text)
        if not number or created is None:
            logger.debug(
                "Skipping OpenAI row without number/date: number=%r created=%r",
                number,
                created_text,
            )
            continue
        if created < start or created > end:
            continue
        if await row.locator(VIEW_LINK).count() == 0:
            logger.debug("Skipping OpenAI invoice %s with no View link", number)
            continue

        listed.append(OpenAIInvoice(number=number, created=created, row_index=index))

    listed.sort(key=lambda inv: (inv.created, inv.number))
    return listed


async def _download_invoice(
    page: Page,
    row_index: int,
    target: Path,
) -> None:
    """Open the Stripe View page for a row and save via Download invoice."""
    view = page.locator(INVOICE_ROW).nth(row_index).locator(VIEW_LINK).first
    async with page.expect_popup(timeout=120_000) as popup_info:
        await view.click()
    invoice_page = await popup_info.value
    try:
        await invoice_page.wait_for_load_state("domcontentloaded")
        button = invoice_page.locator(DOWNLOAD_INVOICE_BUTTON).first
        try:
            await button.wait_for(state="visible", timeout=60_000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "OpenAI Stripe invoice page did not show 'Download invoice'; "
                "confirm the hosted invoice UI still matches selectors"
            ) from exc

        async with invoice_page.expect_download(timeout=120_000) as download_info:
            await button.click()
        download = await download_info.value
        await download.save_as(str(target))
    finally:
        await invoice_page.close()


class OpenAIService:
    """Download all invoice PDFs from OpenAI Platform billing history."""

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
            await page.wait_for_selector(HISTORY_TABLE, timeout=60_000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "OpenAI billing history table did not appear; "
                "confirm Billing → Billing history is reachable and the UI "
                "still matches selectors"
            ) from exc

        invoices = await _listed_invoices(page, start, end)
        if not invoices:
            raise RuntimeError(
                f"No OpenAI invoices found in range "
                f"{start.isoformat()}..{end.isoformat()}"
            )

        saved: list[Path] = []
        for invoice in invoices:
            filename = invoice_filename(name_format, invoice.created, invoice.number)
            # Spec: identical names overwrite (do not append -N suffixes).
            target = output_directory / filename
            await _download_invoice(page, invoice.row_index, target)
            saved.append(target)
            logger.info("Saved OpenAI invoice %s", target)

        return saved
