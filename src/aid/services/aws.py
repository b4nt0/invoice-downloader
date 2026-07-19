"""AWS Billing invoice download automation."""

from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

# Bills page structure (see docs/specs/aws/aws-billing-page.html):
# monthly bills are selected via the billing-period dropdown; PDFs keep only
# the summary card and payer charges-by-service cards.
BILLING_PERIOD_DROPDOWN = "[data-testid='billing-period-dropdown']"
PERIOD_TRIGGER = (
    f"{BILLING_PERIOD_DROPDOWN} button[aria-label='Select billing period']"
)
PERIOD_MENU = "[role='menu'][aria-label='Select billing period']"
SUMMARY_CARD = "[data-testid='summary-card']"
# Account/payer id prefix varies; the suffix is stable (see aws-billing-page.html).
CHARGES_BY_SERVICE_CARD = "[data-testid$='-charges-by-service']"
BILL_SECTION_SELECTORS = (SUMMARY_CARD, CHARGES_BY_SERVICE_CARD)

PERIOD_LABEL_PATTERN = re.compile(
    r"(?:Billing period:\s*)?"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
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


def parse_billing_period(text: str) -> date | None:
    """Parse an AWS billing-period label into the first day of that month."""
    match = PERIOD_LABEL_PATTERN.search(text)
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    return date(int(match.group("year")), month, 1)


def month_overlaps(month_start: date, start: date, end: date) -> bool:
    last_day = monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    return month_start <= end and month_end >= start


def period_option_label(month_start: date) -> str:
    """Format used by the billing-period dropdown (e.g. ``April 2026``)."""
    return month_start.strftime("%B %Y")


async def _wait_for_redirects_to_converge(page: Page) -> None:
    """Wait until AWS login redirects settle on the Bills page.

    The Billing console keeps long-lived connections open, so ``networkidle``
    never arrives; wait for the billing-period control instead.
    """
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_selector(BILLING_PERIOD_DROPDOWN, timeout=60_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "AWS Bills page did not appear after redirects; "
            "confirm the account can open Billing and the UI still matches selectors"
        ) from exc
    await page.locator(PERIOD_TRIGGER).first.wait_for(state="visible", timeout=30_000)


async def _current_billing_period(page: Page) -> date | None:
    trigger = page.locator(PERIOD_TRIGGER).first
    if await trigger.count() == 0:
        return None
    return parse_billing_period((await trigger.inner_text()).strip())


async def _wait_for_bill_period(page: Page, month_start: date) -> None:
    """Wait until the Bills view reflects the selected year/month."""
    desired = period_option_label(month_start)
    try:
        await page.wait_for_function(
            """(label) => {
                const button = document.querySelector(
                    "[data-testid='billing-period-dropdown'] "
                    + "button[aria-label='Select billing period']"
                );
                return !!button && button.textContent.includes(label);
            }""",
            arg=desired,
            timeout=30_000,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"AWS billing period did not switch to {desired}") from exc

    # Prefer the hash query AWS uses after a period change when present.
    period_url = re.compile(
        rf"year={month_start.year}.*month={month_start.month}"
        rf"|month={month_start.month}.*year={month_start.year}"
    )
    try:
        await page.wait_for_url(period_url, timeout=10_000)
    except PlaywrightTimeoutError:
        logger.debug("AWS bill URL did not include year/month for %s", desired)

    summary = page.locator(SUMMARY_CARD)
    if await summary.count() > 0:
        await summary.first.wait_for(state="visible", timeout=30_000)
    charges = page.locator(CHARGES_BY_SERVICE_CARD)
    if await charges.count() > 0:
        await charges.first.wait_for(state="visible", timeout=30_000)


async def _listed_billing_periods(page: Page) -> dict[date, str]:
    """Open the period dropdown and map months to their option labels."""
    trigger = page.locator(PERIOD_TRIGGER).first
    await trigger.click()
    menu = page.locator(PERIOD_MENU)
    try:
        await menu.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("AWS billing-period dropdown did not open") from exc

    items = menu.get_by_role("menuitem")
    count = await items.count()
    listed: dict[date, str] = {}
    for index in range(count):
        label = (await items.nth(index).inner_text()).strip()
        period = parse_billing_period(label)
        if period is not None and period not in listed:
            listed[period] = label

    # Close the menu without changing the selection.
    await page.keyboard.press("Escape")
    try:
        await menu.wait_for(state="hidden", timeout=5_000)
    except PlaywrightTimeoutError:
        await trigger.click()
    return listed


async def _select_billing_period(page: Page, month_start: date, option_label: str) -> None:
    """Select a billing period and wait for the bill view to refresh."""
    desired = period_option_label(month_start)
    current = await _current_billing_period(page)
    if current == month_start:
        await _wait_for_bill_period(page, month_start)
        return

    trigger = page.locator(PERIOD_TRIGGER).first
    await trigger.click()
    menu = page.locator(PERIOD_MENU)
    await menu.wait_for(state="visible", timeout=15_000)

    option = menu.get_by_role("menuitem", name=re.compile(re.escape(option_label)))
    if await option.count() == 0:
        option = menu.get_by_role("menuitem", name=re.compile(re.escape(desired)))
    if await option.count() == 0:
        raise RuntimeError(f"AWS billing period {desired} is not in the dropdown")

    await option.first.click()
    await _wait_for_bill_period(page, month_start)


async def _isolate_bill_sections(page: Page) -> None:
    """Clone bill sections into a clean root and hide the rest of the page."""
    found = await page.evaluate(
        """(selectors) => {
            const root = document.createElement('div');
            root.id = 'aid-print-root';
            root.setAttribute('data-aid-print', 'true');
            let count = 0;
            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    root.appendChild(el.cloneNode(true));
                    count += 1;
                }
            }
            if (count === 0) {
                return 0;
            }
            const style = document.createElement('style');
            style.id = 'aid-print-style';
            style.textContent = `
                body > *:not(#aid-print-root) { display: none !important; }
                #aid-print-root {
                    display: block !important;
                    padding: 16px;
                    background: #fff;
                }
            `;
            document.documentElement.appendChild(style);
            document.body.appendChild(root);
            return count;
        }""",
        list(BILL_SECTION_SELECTORS),
    )
    if not found:
        raise RuntimeError(
            "AWS bill sections not found "
            f"({', '.join(BILL_SECTION_SELECTORS)}); nothing to print"
        )


async def _restore_bill_page(page: Page) -> None:
    await page.evaluate(
        """() => {
            document.getElementById('aid-print-root')?.remove();
            document.getElementById('aid-print-style')?.remove();
        }"""
    )


async def _print_bill_to_pdf(page: Page, target: Path) -> None:
    """Save summary + charges-by-service cards via Chromium print-to-PDF.

    AWS's own Print flow strips chrome from the page; we approximate that by
    cloning only the bill sections into an isolated root before ``page.pdf()``.
    """
    for selector in BILL_SECTION_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=30_000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                f"AWS bill section {selector} did not appear before printing"
            ) from exc

    await _isolate_bill_sections(page)
    await page.emulate_media(media="print")
    try:
        await page.pdf(path=str(target), format="Letter", print_background=True)
    finally:
        await page.emulate_media(media="screen")
        await _restore_bill_page(page)


class AwsService:
    """Download monthly bill PDFs from the AWS Billing console."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        await _wait_for_redirects_to_converge(page)

        target_months = [
            m for m in months_in_range(start, end) if month_overlaps(m, start, end)
        ]
        listed = await _listed_billing_periods(page)

        saved: list[Path] = []
        found_months: set[date] = set()

        for month_start in target_months:
            option_label = listed.get(month_start)
            if option_label is None:
                continue

            await _select_billing_period(page, month_start, option_label)

            filename = format_invoice_name(name_format, month_start)
            target = unique_path(output_directory, filename)
            await _print_bill_to_pdf(page, target)
            saved.append(target)
            found_months.add(month_start)
            logger.info("Saved AWS invoice %s", target)

        missing = sorted(set(target_months) - found_months)
        if missing:
            labels = ", ".join(m.strftime("%Y-%m") for m in missing)
            raise RuntimeError(f"Missing AWS billing periods: {labels}")
        if not saved:
            raise RuntimeError(
                f"No AWS bills found in range {start.isoformat()}..{end.isoformat()}"
            )
        return saved
