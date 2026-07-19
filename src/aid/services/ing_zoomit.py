"""ING Zoomit credit card statement download automation."""

from __future__ import annotations

import asyncio
import logging
import re
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

# Zoomit documents page (see docs/specs/ing-zoomit/zoomit.html):
# History groups months under #sectionHistory; each zoomit-document-item is a
# collapsible row. Credit card statements use subtitle
# "Credit card expenditure statement"; expand → View (PDF).
DOCUMENTS_LIST = "zoomit-documents-list#documentsList, zoomit-documents-list"
HISTORY_SECTION = "#sectionHistory"
MONTH_GROUP = f"{HISTORY_SECTION} > ul > li"
DOCUMENT_ITEM = "zoomit-document-item"
CC_SUBTITLE = "Credit card expenditure statement"
# Text lives in the item's open shadow root; host.inner_text() is empty.
DOCUMENT_SUBTITLE = ".document-item__subtitle"
COLLAPSE_BUTTON = "button.document-itemCollapsible__button"
VIEW_PDF_BUTTON = "#buttonViewPDF"

MONTH_PATTERN = re.compile(
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
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


def month_overlaps(month_start: date, start: date, end: date) -> bool:
    last_day = monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    return month_start <= end and month_end >= start


def parse_month_label(text: str) -> date | None:
    """Parse a Zoomit History group label like ``June 2026``."""
    match = MONTH_PATTERN.search(text)
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    return date(int(match.group("year")), month, 1)


def is_credit_card_statement(text: str) -> bool:
    """Return True when document text is a credit card expenditure statement."""
    return CC_SUBTITLE.lower() in text.lower()


async def _item_subtitle(item: Locator) -> str:
    """Read subtitle text from inside ``zoomit-document-item``'s shadow root."""
    subtitle = item.locator(DOCUMENT_SUBTITLE)
    if await subtitle.count() == 0:
        return ""
    return (await subtitle.first.inner_text()).strip()


async def _is_credit_card_item(item: Locator) -> bool:
    """True when the item's shadow subtitle is a credit card statement."""
    return is_credit_card_statement(await _item_subtitle(item))


async def _wait_for_history(page: Page) -> None:
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(DOCUMENTS_LIST, timeout=60_000)
        await page.wait_for_selector(HISTORY_SECTION, timeout=60_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "ING Zoomit document list did not appear; "
            "confirm Orders → Zoomit is reachable and the UI still matches "
            "selectors"
        ) from exc


async def _listed_statements(page: Page) -> dict[date, Locator]:
    """Map History months to the first credit card statement item locator."""
    groups = page.locator(MONTH_GROUP)
    count = await groups.count()
    listed: dict[date, Locator] = {}

    for index in range(count):
        group = groups.nth(index)
        time_el = group.locator("h2.group-header time").first
        if await time_el.count() == 0:
            continue

        label = (await time_el.inner_text()).strip()
        month_start = parse_month_label(label)
        if month_start is None:
            logger.debug("Skipping Zoomit group without parseable month: %r", label)
            continue
        if month_start in listed:
            continue

        items = group.locator(DOCUMENT_ITEM)
        item_count = await items.count()
        for item_index in range(item_count):
            item = items.nth(item_index)
            if not await _is_credit_card_item(item):
                continue
            listed[month_start] = item
            break

    return listed


async def _expand_item(item: Locator) -> None:
    """Expand a Zoomit document collapsible if it is collapsed."""
    invoker = item.locator(COLLAPSE_BUTTON).first
    try:
        await invoker.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "ING Zoomit statement row has no expand control; "
            "confirm the Zoomit document item UI still matches selectors"
        ) from exc

    expanded = (await invoker.get_attribute("aria-expanded")) or "false"
    if expanded.lower() != "true":
        await invoker.click()


async def _wait_for_enabled_pdf_button(item: Locator, timeout_ms: float = 30_000) -> Locator:
    """Wait until View (PDF) is visible and not disabled inside an expanded item."""
    button = item.locator(VIEW_PDF_BUTTON).first
    try:
        await button.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "ING Zoomit 'View (PDF)' control did not appear after expanding "
            "a credit card statement"
        ) from exc

    deadline = timeout_ms / 1000
    elapsed = 0.0
    while elapsed < deadline:
        disabled = await button.get_attribute("disabled")
        aria_disabled = (await button.get_attribute("aria-disabled")) or "false"
        if disabled is None and aria_disabled.lower() != "true":
            return button
        await item.page.wait_for_timeout(200)
        elapsed += 0.2

    raise RuntimeError(
        "ING Zoomit 'View (PDF)' stayed disabled; "
        "confirm the statement PDF is available for download"
    )


def _is_pdf_helper_tab(tab: Page) -> bool:
    """True for blob/PDF/about tabs spawned by View (PDF), not the banking UI."""
    url = (tab.url or "").strip().lower()
    return (
        url.startswith("blob:")
        or url.startswith("about:")
        or url.endswith(".pdf")
        or "application/pdf" in url
    )


async def _restore_zoomit_page(
    context: BrowserContext,
    page: Page,
    zoomit_url: str,
) -> Page:
    """Return a live Zoomit History page after View (PDF).

    The PDF flow often opens a blob tab and/or tears down the original page.
    Reopen Zoomit in the same browser context so later months can download.
    """
    try:
        pages = list(context.pages)
    except Exception as exc:
        raise RuntimeError(
            "ING Zoomit browser context closed after View (PDF); "
            "cannot continue downloading remaining months"
        ) from exc

    survivors = [p for p in pages if not p.is_closed()]

    for extra in survivors:
        if extra is page:
            continue
        if not _is_pdf_helper_tab(extra):
            continue
        try:
            await extra.close()
        except Exception:
            logger.debug("Could not close Zoomit PDF helper tab", exc_info=True)

    survivors = [p for p in context.pages if not p.is_closed()]
    if not page.is_closed():
        active = page
    else:
        zoomit_tabs = [p for p in survivors if "zoomit" in (p.url or "").lower()]
        if zoomit_tabs:
            active = zoomit_tabs[0]
        elif survivors:
            active = survivors[0]
        else:
            active = await context.new_page()

    try:
        await active.bring_to_front()
    except Exception:
        logger.debug("Could not focus Zoomit page", exc_info=True)

    on_zoomit = "zoomit" in (active.url or "").lower()
    if active.is_closed() or not on_zoomit:
        if active.is_closed():
            active = await context.new_page()
        logger.info("Reopening ING Zoomit after PDF download")
        await active.goto(zoomit_url, wait_until="domcontentloaded")

    await _wait_for_history(active)
    return active


async def _download_statement(page: Page, item: Locator, target: Path) -> Page:
    """Expand a statement row, click View (PDF), save the PDF, restore Zoomit.

    Returns a live page still on the Zoomit History list (may be a new tab if
    View (PDF) closed the original page).
    """
    zoomit_url = page.url
    context = page.context

    await _expand_item(item)
    button = await _wait_for_enabled_pdf_button(item)

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

    for existing in context.pages:
        _attach_page(existing)
    context.on("page", _attach_page)

    try:
        await button.click()
        try:
            download = await asyncio.wait_for(
                asyncio.shield(download_future), timeout=120
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                "ING Zoomit PDF download did not start after View (PDF)"
            ) from exc
        await download.save_as(str(target))
    finally:
        try:
            context.remove_listener("page", _attach_page)
        except Exception:
            logger.debug("Could not detach Zoomit page listener", exc_info=True)
        for attached in attached_pages:
            try:
                attached.remove_listener("download", _capture_download)
            except Exception:
                logger.debug(
                    "Could not detach Zoomit download listener",
                    exc_info=True,
                )

    return await _restore_zoomit_page(context, page, zoomit_url)


class IngZoomitService:
    """Download monthly credit card statement PDFs from ING Zoomit."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        await _wait_for_history(page)

        target_months = {
            m for m in months_in_range(start, end) if month_overlaps(m, start, end)
        }

        saved: list[Path] = []
        found_months: set[date] = set()
        active = page

        for month_start in sorted(target_months):
            # Re-scan after each download: View (PDF) may rebuild the list or
            # replace the page, invalidating earlier locators.
            listed = await _listed_statements(active)
            item = listed.get(month_start)
            if item is None:
                continue

            filename = format_invoice_name(name_format, month_start)
            target = unique_path(output_directory, filename)
            active = await _download_statement(active, item, target)
            saved.append(target)
            found_months.add(month_start)
            logger.info("Saved ING Zoomit statement %s", target)

        missing = sorted(target_months - found_months)
        if missing:
            labels = ", ".join(m.strftime("%Y-%m") for m in missing)
            raise RuntimeError(
                f"Missing ING Zoomit credit card statements for months: {labels}"
            )
        if not saved:
            raise RuntimeError(
                f"No ING Zoomit credit card statements found in range "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        return saved
