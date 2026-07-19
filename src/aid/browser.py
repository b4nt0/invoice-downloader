"""Playwright browser session helpers."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

SESSIONS_DIR = Path(".aid") / "sessions"


def session_path(service_name: str, *, base: Path | None = None) -> Path:
    """Return the storage_state path for a service."""
    root = (base or Path.cwd()) / SESSIONS_DIR
    return root / f"{service_name}.json"


async def start_playwright() -> Playwright:
    return await async_playwright().start()


async def launch_browser(playwright: Playwright, *, headless: bool) -> Browser:
    return await playwright.chromium.launch(headless=headless)


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


async def new_page(context: BrowserContext) -> Page:
    return await context.new_page()


async def save_storage_state(context: BrowserContext, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))


def url_without_query(url: str) -> str:
    """Strip query string and fragment for login URL comparisons."""
    without_fragment = url.split("#", 1)[0]
    return without_fragment.split("?", 1)[0]


def urls_match_ignoring_query(actual: str, expected: str) -> bool:
    """Return True if *actual* matches *expected* ignoring query/fragment."""
    actual_base = url_without_query(actual).rstrip("/")
    expected_base = url_without_query(expected).rstrip("/")
    return actual_base == expected_base or actual_base.startswith(expected_base + "/")
