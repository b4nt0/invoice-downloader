"""AWS Billing invoice download automation."""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from playwright.async_api import Download, Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

# Selectors for the AWS Billing invoices table (UI is volatile).
INVOICE_TABLE = "table, [data-testid='invoices-table'], .awsui-table"
INVOICE_ROW = "tbody tr, [role='row']"
DOWNLOAD_LINK = "a:has-text('Download'), button:has-text('Download'), a[href*='invoice']"
DATE_PATTERN = re.compile(
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
    r"|"
    r"(?P<iso>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_invoice_date(text: str) -> date | None:
    """Extract an invoice date from a table cell or row label."""
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    if match.group("iso"):
        return date.fromisoformat(match.group("iso"))
    month = MONTHS[match.group("month")[:3].lower()]
    return date(int(match.group("year")), month, int(match.group("day")))


class AwsService:
    """Download invoice PDFs from the AWS Billing console."""

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
                "AWS invoices table did not appear; "
                "confirm the account has invoices and the UI still matches selectors"
            ) from exc

        rows = page.locator(INVOICE_ROW)
        count = await rows.count()
        saved: list[Path] = []

        for index in range(count):
            row = rows.nth(index)
            text = (await row.inner_text()).strip()
            invoice_date = parse_invoice_date(text)
            if invoice_date is None:
                logger.debug("Skipping AWS row without parseable date: %s", text[:80])
                continue
            if invoice_date < start or invoice_date > end:
                continue

            download_control = row.locator(DOWNLOAD_LINK).first
            if await download_control.count() == 0:
                # Some layouts put the download control outside the text row.
                download_control = row.get_by_role("link", name=re.compile("download", re.I))
                if await download_control.count() == 0:
                    download_control = row.get_by_role(
                        "button", name=re.compile("download", re.I)
                    )
            if await download_control.count() == 0:
                raise RuntimeError(
                    f"AWS invoice row for {invoice_date.isoformat()} has no download control"
                )

            async with page.expect_download(timeout=120_000) as download_info:
                await download_control.first.click()
            download: Download = await download_info.value

            filename = format_invoice_name(name_format, invoice_date)
            target = unique_path(output_directory, filename)
            await download.save_as(str(target))
            saved.append(target)
            logger.info("Saved AWS invoice %s", target)

        if not saved:
            raise RuntimeError(
                f"No AWS invoices found in range {start.isoformat()}..{end.isoformat()}"
            )
        return saved
