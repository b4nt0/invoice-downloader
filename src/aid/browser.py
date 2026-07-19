"""Playwright browser session helpers."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from aid.debug import ActionTracer

SESSIONS_DIR = Path(".aid") / "sessions"


def session_path(service_name: str, *, base: Path | None = None) -> Path:
    """Return the storage_state path for a service."""
    root = (base or Path.cwd()) / SESSIONS_DIR
    return root / f"{service_name}.json"


async def start_playwright() -> Playwright:
    return await async_playwright().start()


async def launch_browser(
    playwright: Playwright,
    *,
    headless: bool,
    slow_mo_ms: float = 0,
) -> Browser:
    kwargs: dict = {"headless": headless}
    if slow_mo_ms:
        kwargs["slow_mo"] = slow_mo_ms
    return await playwright.chromium.launch(**kwargs)


async def new_context(
    browser: Browser,
    *,
    storage_state: Path | None = None,
    accept_downloads: bool = True,
) -> BrowserContext:
    kwargs: dict = {"accept_downloads": accept_downloads}
    if storage_state is not None and storage_state.is_file():
        kwargs["storage_state"] = str(storage_state)
    return await browser.new_context(**kwargs)


async def new_page(
    context: BrowserContext,
    *,
    tracer: ActionTracer | None = None,
) -> Page:
    page = await context.new_page()
    if tracer is not None:
        return tracer.instrument_page(page)
    return page


async def save_storage_state(context: BrowserContext, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))


def url_without_query(url: str) -> str:
    """Strip query string and fragment for login URL comparisons."""
    without_fragment = url.split("#", 1)[0]
    return without_fragment.split("?", 1)[0]


def urls_match_ignoring_query(actual: str, expected: str) -> bool:
    """Return True if *actual* matches *expected* ignoring query/fragment.

    Treats *expected* as a path prefix, so ``https://example.com/login/extra``
    matches ``https://example.com/login``.
    """
    actual_base = url_without_query(actual).rstrip("/")
    expected_base = url_without_query(expected).rstrip("/")
    return actual_base == expected_base or actual_base.startswith(expected_base + "/")


def urls_match_exact_path_ignoring_query(actual: str, expected: str) -> bool:
    """Return True if *actual* and *expected* share scheme, host, and path.

    Query strings and fragments are ignored. Unlike
    :func:`urls_match_ignoring_query`, a longer path does not match a shorter
    prefix.
    """
    actual_base = url_without_query(actual).rstrip("/")
    expected_base = url_without_query(expected).rstrip("/")
    return actual_base == expected_base


def is_login_url_redirect(current_url: str, login_url: str, dashboard_url: str) -> bool:
    """Return True if *current_url* looks like a redirect to *login_url*.

    Normally compares with path-prefix matching (query ignored). When
    *login_url* is itself a prefix of *dashboard_url* (or equal under that
    comparison), prefix matching would treat the dashboard as a login page, so
    the check falls back to an exact path match instead.
    """
    if urls_match_ignoring_query(dashboard_url, login_url):
        return urls_match_exact_path_ignoring_query(current_url, login_url)
    return urls_match_ignoring_query(current_url, login_url)
