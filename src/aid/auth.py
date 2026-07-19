"""Authentication probe and interactive login flow."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright
from playwright.async_api import Error as PlaywrightError

from aid.browser import (
    launch_browser,
    new_context,
    new_page,
    save_storage_state,
    session_path,
    urls_match_ignoring_query,
)
from aid.config import ServiceConfig
from aid.debug import ActionTracer

logger = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    """Raised when authentication cannot be completed."""


@dataclass
class AuthenticatedSession:
    """An authenticated browser session ready for download."""

    browser: Browser
    context: BrowserContext
    page: Page
    service: ServiceConfig


def title_has_login_marker(title: str, markers: list[str]) -> bool:
    """Return True if the page title contains any login marker."""
    lowered = title.lower()
    return any(marker.lower() in lowered for marker in markers)


async def probe_authentication(
    page: Page,
    service: ServiceConfig,
    login_markers: list[str],
) -> bool:
    """Navigate to the dashboard and return True if still authenticated."""
    await page.goto(service.dashboard_url, wait_until="domcontentloaded")
    current_url = page.url
    if urls_match_ignoring_query(current_url, service.login_url):
        return False
    title = await page.title()
    if title_has_login_marker(title, login_markers):
        return False
    return True


async def wait_for_enter(*, prompt: str | None = None) -> None:
    """Block until the user presses Enter in the console."""
    if prompt:
        print(prompt, flush=True)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sys.stdin.readline)


async def wait_for_interactive_completion(
    *,
    timeout_ms: float,
    wait_for_enter_fn=wait_for_enter,
) -> None:
    """Wait until the user presses Enter to confirm interactive login is done.

    URL-based auto-detect is intentionally not used: SSO/OAuth flows often leave
    the configured ``login_url`` (or open a new tab) long before authentication
    finishes, which would close the browser too early.
    """
    try:
        await asyncio.wait_for(
            wait_for_enter_fn(
                prompt=(
                    "Finish signing in in the browser (new tabs / SSO redirects are fine). "
                    "Leave the window open, then press Enter here to save the session "
                    "and continue."
                )
            ),
            timeout=timeout_ms / 1000.0,
        )
    except TimeoutError as exc:
        raise AuthenticationError("Timed out waiting for interactive login") from exc


async def interactive_login(
    playwright: Playwright,
    service: ServiceConfig,
    *,
    session_file: Path,
    timeout_ms: float = 600_000,
    wait_for_enter_fn=wait_for_enter,
    slow_mo_ms: float = 0,
    tracer: ActionTracer | None = None,
) -> None:
    """Open a headed browser for the user to sign in, then persist the session."""
    if tracer:
        tracer.log("starting interactive login")
    browser = await launch_browser(playwright, headless=False, slow_mo_ms=slow_mo_ms)
    try:
        context = await new_context(browser)
        page = await new_page(context, tracer=tracer)
        await page.goto(service.login_url, wait_until="domcontentloaded")
        logger.info(
            "Interactive login for '%s': complete sign-in in the browser, "
            "then press Enter in this terminal. AID will not close the browser "
            "until you do.",
            service.name,
        )

        await wait_for_interactive_completion(
            timeout_ms=timeout_ms,
            wait_for_enter_fn=wait_for_enter_fn,
        )
        await save_storage_state(context, session_file)
        if tracer:
            tracer.log(f"saved session → {session_file}")
        logger.info("Saved session for '%s'", service.name)
    except PlaywrightError as exc:
        if "closed" in str(exc).lower():
            raise AuthenticationError(
                f"Browser was closed during login for '{service.name}'. "
                "Finish signing in and leave the window open — "
                "press Enter in the terminal when done, then AID closes the browser."
            ) from exc
        raise
    finally:
        try:
            await browser.close()
        except PlaywrightError:
            pass


async def authenticate(
    playwright: Playwright,
    service: ServiceConfig,
    login_markers: list[str],
    *,
    base: Path | None = None,
    allow_interactive: bool = True,
    headed: bool = False,
    slow_mo_ms: float = 0,
    tracer: ActionTracer | None = None,
) -> AuthenticatedSession:
    """Authenticate a service: probe saved session, fall back to interactive once.

    Interactive authentication is attempted at most once per call. If the
    subsequent probe still fails, ``AuthenticationError`` is raised.

    When *headed* is True (debug mode), probe/download browsers are visible.
    """
    session_file = session_path(service.name, base=base)
    interactive_used = False

    if not session_file.is_file():
        if not allow_interactive:
            raise AuthenticationError(
                f"No saved session for '{service.name}' and interactive login disabled"
            )
        if tracer:
            tracer.log("no saved session; launching interactive login")
        await interactive_login(
            playwright,
            service,
            session_file=session_file,
            wait_for_enter_fn=wait_for_enter,
            slow_mo_ms=slow_mo_ms,
            tracer=tracer,
        )
        interactive_used = True

    if tracer:
        tracer.log(
            f"auth probe (headed={headed}) using session "
            f"{'present' if session_file.is_file() else 'missing'}"
        )
    browser = await launch_browser(
        playwright, headless=not headed, slow_mo_ms=slow_mo_ms
    )
    context = await new_context(browser, storage_state=session_file)
    page = await new_page(context, tracer=tracer)

    if await probe_authentication(page, service, login_markers):
        await save_storage_state(context, session_file)
        if tracer:
            tracer.log("auth probe succeeded")
        return AuthenticatedSession(
            browser=browser, context=context, page=page, service=service
        )

    if tracer:
        tracer.log("auth probe failed")
    await browser.close()

    if interactive_used or not allow_interactive:
        raise AuthenticationError(
            f"Authentication failed for '{service.name}' "
            f"(interactive login already attempted or disabled)"
        )

    await interactive_login(
        playwright,
        service,
        session_file=session_file,
        slow_mo_ms=slow_mo_ms,
        tracer=tracer,
    )

    if tracer:
        tracer.log(f"auth probe after interactive login (headed={headed})")
    browser = await launch_browser(
        playwright, headless=not headed, slow_mo_ms=slow_mo_ms
    )
    context = await new_context(browser, storage_state=session_file)
    page = await new_page(context, tracer=tracer)

    if not await probe_authentication(page, service, login_markers):
        if tracer:
            tracer.log("auth probe failed after interactive login")
        await browser.close()
        raise AuthenticationError(
            f"Authentication failed for '{service.name}' after interactive login"
        )

    await save_storage_state(context, session_file)
    if tracer:
        tracer.log("auth probe succeeded after interactive login")
    return AuthenticatedSession(
        browser=browser, context=context, page=page, service=service
    )
