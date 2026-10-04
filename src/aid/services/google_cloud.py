"""Google Cloud Billing invoice download automation."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import Frame, FrameLocator, Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, record_missing_invoices, unique_path

logger = logging.getLogger(__name__)

# Invoices page (live Payments document center; see docs/specs/gcp/gcp.md):
# the list lives in iframe[name=billing-iframeIframe]. There is no per-row
# Download link. Open a row → Actions → Download → "Download documents"
# pop-up form (temporary Payments iframe) → Download (PDF).
# The invoice detail is a flyout. Its close control is .b3id-section-close.
# Collapsing the flyout keeps the Actions button in the DOM (off-screen), so
# "closed" means the flyout no longer has the expanded class.
BILLING_IFRAME = 'iframe[name="billing-iframeIframe"]'
DOCUMENT_ROW = "tr.b3id-widget-table-data-row"
DOCUMENT_NUMBER_CELL = '[aria-label="Document number"]'
FORM_DOWNLOAD_BUTTON = (
    '[role="button"].b3-primary-button:has-text("Download")'
)
EXPANDED_FLYOUT = ".b3-section.flyout.expanded"
DETAIL_CLOSE = (
    ".b3-section.flyout.expanded .b3id-section-close, "
    ".b3id-widget-component-close-icon, "
    ".b3-widget-component-close-icon, "
    '[aria-label="Close dialog"]'
)
COOKIE_OK = 'button:has-text("OK, got it")'

INVOICE_TYPE_PATTERN = re.compile(r"\b(?:invoice|statement)\b", re.IGNORECASE)
TAX_TYPE_PATTERN = re.compile(r"\b(?:tax|vat)\b", re.IGNORECASE)

DATE_PATTERNS = (
    re.compile(
        r"(?P<day>\d{1,2})\s+"
        r"(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<month>January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+(?P<year>\d{4})",
        re.IGNORECASE,
    ),
    re.compile(r"(?P<year>\d{4})-(?P<month_num>\d{1,2})-(?P<day>\d{1,2})"),
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
    return True


async def _dismiss_cookies(page: Page) -> None:
    button = page.locator(COOKIE_OK).first
    try:
        if await button.count() and await button.is_visible():
            await button.click(timeout=3_000)
    except PlaywrightTimeoutError:
        logger.debug("Cookie banner not dismissed")


async def _billing_frame(page: Page) -> FrameLocator:
    """Wait for the Payments billing iframe and return a frame locator."""
    await page.wait_for_load_state("domcontentloaded")
    await _dismiss_cookies(page)

    try:
        await page.wait_for_selector(BILLING_IFRAME, timeout=60_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Google Cloud billing invoices iframe did not appear; "
            "confirm Billing → Invoices is reachable for the configured "
            "billing account and the UI still matches selectors"
        ) from exc

    frame = page.frame_locator(BILLING_IFRAME)
    try:
        await frame.locator(DOCUMENT_ROW).first.wait_for(
            state="visible", timeout=60_000
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Google Cloud document list did not appear inside the "
            "Payments iframe; confirm the billing account has invoices "
            "and the UI still matches selectors"
        ) from exc
    await _dismiss_cookies(page)
    return frame


async def _listed_documents(frame: FrameLocator) -> list[tuple[date, int]]:
    """Map visible invoice/statement rows to (month_start, row_index)."""
    rows = frame.locator(DOCUMENT_ROW)
    count = await rows.count()
    listed: list[tuple[date, int]] = []

    for index in range(count):
        text = (await rows.nth(index).inner_text()).strip()
        if not text or not is_invoice_document(text):
            continue

        document_date = parse_document_date(text)
        if document_date is None:
            logger.debug(
                "Skipping Google Cloud document without parseable date: %r", text
            )
            continue

        month_start = date(document_date.year, document_date.month, 1)
        listed.append((month_start, index))

    return listed


async def _wait_download_form_frame(page: Page, timeout_ms: float = 60_000) -> Frame:
    """Return the temporary Payments iframe that hosts Download documents."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for frame in page.frames:
            if frame.name == "billing-iframeIframe":
                continue
            try:
                has_title = await frame.locator("text=Download documents").count() > 0
                has_pdf = await frame.locator("text=PDF invoices").count() > 0
                has_button = (
                    await frame.locator(FORM_DOWNLOAD_BUTTON).count() > 0
                )
                if (has_title and has_pdf) or (
                    has_pdf and has_button and (frame.name or "").startswith("tempId-")
                ):
                    button = frame.locator(FORM_DOWNLOAD_BUTTON).first
                    await button.wait_for(state="visible", timeout=5_000)
                    class_name = (await button.get_attribute("class")) or ""
                    if "jfk-button-disabled" not in class_name:
                        return frame
            except Exception:
                continue
        await page.wait_for_timeout(200)
    raise RuntimeError(
        "Google Cloud 'Download documents' form did not appear; "
        "confirm Actions → Download still opens the PDF/CSV pop-up"
    )


async def _close_overlays(page: Page, frame: FrameLocator | None = None) -> None:
    """Dismiss download form and invoice detail so the next row is clickable."""
    try:
        await page.bring_to_front()
    except Exception:
        logger.debug("Could not focus billing page before closing overlays", exc_info=True)

    # Parent-page modal shell for the Download documents form.
    parent_close = page.locator(
        '.modal-dialog [aria-label="Close"], '
        ".modal-dialog .modal-dialog-title-close, "
        ".b3id-modal-dialog-title [role='button']"
    )
    try:
        if await parent_close.count() and await parent_close.first.is_visible():
            await parent_close.first.click(force=True, timeout=3_000)
            await page.wait_for_timeout(300)
    except Exception:
        logger.debug("Parent download modal close skipped", exc_info=True)

    if frame is not None:
        # Invoice detail flyout close (X) inside the Payments iframe.
        # A normal click collapses it; force is only a fallback when the
        # control sits on the iframe edge and fails hit-testing.
        detail_close = frame.locator(DETAIL_CLOSE)
        try:
            count = await detail_close.count()
            for index in range(count):
                icon = detail_close.nth(index)
                if not await icon.is_visible():
                    continue
                try:
                    await icon.click(timeout=3_000)
                except Exception:
                    await icon.click(force=True, timeout=3_000)
                await page.wait_for_timeout(200)
        except Exception:
            logger.debug("Invoice detail close icon click skipped", exc_info=True)

    for _ in range(3):
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)

    if frame is not None:
        # Collapsed flyouts leave the Actions button in the DOM, so wait until
        # the expanded flyout itself is gone rather than until Actions is hidden.
        try:
            await frame.locator(EXPANDED_FLYOUT).wait_for(state="hidden", timeout=5_000)
        except PlaywrightTimeoutError:
            logger.debug("Invoice detail flyout still expanded after close attempts")


async def _close_helper_pages(page: Page) -> None:
    """Close blank helper tabs spawned by the Payments download flow.

    Only ``about:blank`` tabs are closed. Never close Cloud Console pages —
    Payments sometimes opens a second invoices tab that must not be killed.
    """
    for extra in list(page.context.pages):
        if extra is page:
            continue
        url = (extra.url or "").strip().lower()
        if not (url.startswith("about:blank") or url == ""):
            logger.debug("Leaving Google Cloud extra tab open (%s)", extra.url)
            continue
        try:
            await extra.close()
            logger.debug("Closed Google Cloud download popup tab (%s)", extra.url)
        except Exception:
            logger.debug("Failed to close Google Cloud popup tab", exc_info=True)


async def _download_via_form(page: Page, form: Frame, target: Path) -> None:
    """Confirm PDF on the pop-up form and save via the browser download event.

    Payments opens a blank helper tab that owns the download event, so listeners
    must cover every page in the context. The ``get_document_archive`` network
    response cannot be read with ``Response.body()`` (Chrome discards it).
    """
    download_button = form.locator(FORM_DOWNLOAD_BUTTON).first
    try:
        await download_button.wait_for(state="visible", timeout=30_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Google Cloud download form did not show a Download button"
        ) from exc

    class_name = (await download_button.get_attribute("class")) or ""
    if "jfk-button-disabled" in class_name:
        raise RuntimeError(
            "Google Cloud download form Download button is disabled; "
            "confirm PDF invoices is selected"
        )

    loop = asyncio.get_running_loop()
    download_future: asyncio.Future = loop.create_future()
    attached_pages: set[Page] = set()

    def _capture_download(download) -> None:
        if not download_future.done():
            download_future.set_result(download)

    def _attach_page(popup: Page) -> None:
        if popup in attached_pages:
            return
        attached_pages.add(popup)
        popup.on("download", _capture_download)

    for existing in page.context.pages:
        _attach_page(existing)
    page.context.on("page", _attach_page)

    try:
        await download_button.click(force=True)
        try:
            download = await asyncio.wait_for(
                asyncio.shield(download_future), timeout=120
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "Google Cloud download did not start after confirming the "
                "Download documents form"
            ) from exc

        await download.save_as(str(target))
        logger.debug("Saved Google Cloud invoice download → %s", target)
    finally:
        try:
            page.context.remove_listener("page", _attach_page)
        except Exception:
            logger.debug("Could not detach Google Cloud page listener", exc_info=True)
        for attached in attached_pages:
            try:
                attached.remove_listener("download", _capture_download)
            except Exception:
                logger.debug(
                    "Could not detach Google Cloud download listeners",
                    exc_info=True,
                )
        await page.wait_for_timeout(300)
        await _close_helper_pages(page)
        try:
            await page.bring_to_front()
        except Exception:
            logger.debug("Could not focus Google Cloud billing page", exc_info=True)


async def _download_document(
    page: Page,
    frame: FrameLocator,
    row_index: int,
    target: Path,
) -> None:
    """Open a row, run Actions → Download, confirm the pop-up form, save PDF."""
    # Ensure a previous invoice detail / download modal is not blocking rows.
    await _close_overlays(page, frame)

    row = frame.locator(DOCUMENT_ROW).nth(row_index)
    # force=True: the document-center panel can intercept normal hit-testing.
    await row.locator(DOCUMENT_NUMBER_CELL).click(force=True)
    try:
        actions = frame.get_by_role("button", name="Actions")
        await actions.wait_for(state="visible", timeout=30_000)
        await actions.click()
        menu_item = frame.get_by_role("menuitem", name="Download")
        await menu_item.wait_for(state="visible", timeout=15_000)
        await menu_item.click()
        form = await _wait_download_form_frame(page)
        await _download_via_form(page, form, target)
    finally:
        await _close_overlays(page, frame)
        await _close_helper_pages(page)


class GoogleCloudService:
    """Download monthly invoice PDFs from Google Cloud Billing → Invoices."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        frame = await _billing_frame(page)

        target_months = {
            m for m in months_in_range(start, end) if month_overlaps(m, start, end)
        }
        listed = await _listed_documents(frame)

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
            logger.info("Saved Google Cloud invoice %s", target)

        missing = sorted(target_months - found_months)
        saved.extend(
            record_missing_invoices(
                missing,
                directory=output_directory,
                name_format=name_format,
                service_label="Google Cloud invoice",
                log=logger,
            )
        )
        if not saved:
            raise RuntimeError(
                f"No Google Cloud invoices found in range "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        return saved
