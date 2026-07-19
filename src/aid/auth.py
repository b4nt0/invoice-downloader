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
    is_login_url_redirect,
    launch_browser,
    launch_persistent_context,
    new_context,
    new_page,
    resolve_user_data_dir,
    save_storage_state,
    session_path,
)
from aid.config import ServiceConfig
from aid.debug import ActionTracer

logger = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    """Raised when authentication cannot be completed."""


@dataclass
class AuthenticatedSession:
    """An authenticated browser session ready for download."""

    browser: Browser | None
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
    logger.debug(
        "Auth probe for '%s': navigating to dashboard %s",
        service.name,
        service.dashboard_url,
    )
    await page.goto(service.dashboard_url, wait_until="domcontentloaded")
    current_url = page.url
    if is_login_url_redirect(current_url, service.login_url, service.dashboard_url):
        logger.debug(
            "Auth probe for '%s' failed: redirected to login URL %s",
            service.name,
            current_url,
        )
        return False
    title = await page.title()
    if title_has_login_marker(title, login_markers):
        logger.debug(
            "Auth probe for '%s' failed: redirected to a page whose title "
            "matches a login marker (url=%s, title=%r, markers=%s)",
            service.name,
            current_url,
            title,
            login_markers,
        )
        return False
    if service.dashboard_marker is not None:
        await page.wait_for_load_state("load")
        try:
            await page.wait_for_function(
                "(marker) => document.documentElement.outerHTML.includes(marker)",
                arg=service.dashboard_marker,
                timeout=5_000,
            )
        except PlaywrightError:
            logger.debug(
                "Auth probe for '%s' failed: dashboard marker %r not detected "
                "on %s (title=%r)",
                service.name,
                service.dashboard_marker,
                current_url,
                title,
            )
            return False
    logger.debug(
        "Auth probe for '%s' succeeded (url=%s, title=%r)",
        service.name,
        current_url,
        title,
    )
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


async def _close_browser(browser: Browser | None) -> None:
    if browser is None:
        return
    try:
        await browser.close()
    except PlaywrightError:
        pass


async def _close_context(context: BrowserContext | None) -> None:
    if context is None:
        return
    try:
        await context.close()
    except PlaywrightError:
        pass


def _profile_dir(service: ServiceConfig, base: Path | None) -> Path:
    assert service.user_data_dir is not None
    return resolve_user_data_dir(service.user_data_dir, base=base)


async def _open_persistent_session(
    playwright: Playwright,
    service: ServiceConfig,
    *,
    base: Path | None,
    headless: bool,
    slow_mo_ms: float,
    tracer: ActionTracer | None,
) -> tuple[Browser | None, BrowserContext, Page]:
    context = await launch_persistent_context(
        playwright,
        _profile_dir(service, base),
        headless=headless,
        slow_mo_ms=slow_mo_ms,
        channel=service.browser_channel,
    )
    page = await new_page(context, tracer=tracer)
    return context.browser, context, page


async def interactive_login(
    playwright: Playwright,
    service: ServiceConfig,
    *,
    session_file: Path,
    timeout_ms: float = 600_000,
    wait_for_enter_fn=wait_for_enter,
    slow_mo_ms: float = 0,
    tracer: ActionTracer | None = None,
    base: Path | None = None,
) -> None:
    """Open a headed browser for the user to sign in, then persist the session."""
    if tracer:
        tracer.log("starting interactive login")

    if service.user_data_dir:
        # Profile on disk is the session; no storage_state JSON.
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            browser, context, page = await _open_persistent_session(
                playwright,
                service,
                base=base,
                headless=False,
                slow_mo_ms=slow_mo_ms,
                tracer=tracer,
            )
            await page.goto(service.login_url, wait_until="domcontentloaded")
            logger.info(
                "Interactive login for '%s': complete sign-in in the browser, "
                "then press Enter in this terminal. The Chrome profile under "
                "%s keeps the session.",
                service.name,
                _profile_dir(service, base),
            )
            await wait_for_interactive_completion(
                timeout_ms=timeout_ms,
                wait_for_enter_fn=wait_for_enter_fn,
            )
            if tracer:
                tracer.log(f"persistent profile ready → {_profile_dir(service, base)}")
            logger.info("Saved session for '%s' (browser profile)", service.name)
        except PlaywrightError as exc:
            if "closed" in str(exc).lower():
                raise AuthenticationError(
                    f"Browser was closed during login for '{service.name}'. "
                    "Finish signing in and leave the window open — "
                    "press Enter in the terminal when done, then AID closes the browser."
                ) from exc
            raise
        finally:
            await _close_context(context)
        return

    browser = await launch_browser(
        playwright,
        headless=False,
        slow_mo_ms=slow_mo_ms,
        channel=service.browser_channel,
    )
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
        await _close_browser(browser)


async def _authenticate_with_storage_state(
    playwright: Playwright,
    service: ServiceConfig,
    login_markers: list[str],
    *,
    base: Path | None,
    allow_interactive: bool,
    headed: bool,
    slow_mo_ms: float,
    tracer: ActionTracer | None,
) -> AuthenticatedSession:
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
            base=base,
        )
        interactive_used = True

    if tracer:
        tracer.log(
            f"auth probe (headed={headed}) using session "
            f"{'present' if session_file.is_file() else 'missing'}"
        )
    browser = await launch_browser(
        playwright,
        headless=not headed,
        slow_mo_ms=slow_mo_ms,
        channel=service.browser_channel,
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
    await _close_browser(browser)

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
        base=base,
    )

    if tracer:
        tracer.log(f"auth probe after interactive login (headed={headed})")
    browser = await launch_browser(
        playwright,
        headless=not headed,
        slow_mo_ms=slow_mo_ms,
        channel=service.browser_channel,
    )
    context = await new_context(browser, storage_state=session_file)
    page = await new_page(context, tracer=tracer)

    if not await probe_authentication(page, service, login_markers):
        if tracer:
            tracer.log("auth probe failed after interactive login")
        await _close_browser(browser)
        raise AuthenticationError(
            f"Authentication failed for '{service.name}' after interactive login"
        )

    await save_storage_state(context, session_file)
    if tracer:
        tracer.log("auth probe succeeded after interactive login")
    return AuthenticatedSession(
        browser=browser, context=context, page=page, service=service
    )


async def _authenticate_with_profile(
    playwright: Playwright,
    service: ServiceConfig,
    login_markers: list[str],
    *,
    base: Path | None,
    allow_interactive: bool,
    headed: bool,  # noqa: ARG001 — profiles always run headed
    slow_mo_ms: float,
    tracer: ActionTracer | None,
) -> AuthenticatedSession:
    """Authenticate using a persistent Chrome profile (not storage_state JSON).

    Headless is avoided for profile sessions: Cloudflare/Auth0 often reject
    headless even when the on-disk profile is valid.
    """
    profile = _profile_dir(service, base)
    # Persistent profiles stay headed: Cloudflare/Auth0 often reject headless
    # even when the on-disk profile is valid.
    headless = False

    if tracer:
        tracer.log(
            f"auth probe via persistent profile {profile} "
            f"(channel={service.browser_channel or 'chromium'})"
        )

    browser, context, page = await _open_persistent_session(
        playwright,
        service,
        base=base,
        headless=headless,
        slow_mo_ms=slow_mo_ms,
        tracer=tracer,
    )

    if await probe_authentication(page, service, login_markers):
        if tracer:
            tracer.log("auth probe succeeded")
        return AuthenticatedSession(
            browser=browser, context=context, page=page, service=service
        )

    if tracer:
        tracer.log("auth probe failed")
    await _close_context(context)

    if not allow_interactive:
        raise AuthenticationError(
            f"Authentication failed for '{service.name}' "
            f"(interactive login disabled; profile {profile})"
        )

    await interactive_login(
        playwright,
        service,
        session_file=session_path(service.name, base=base),
        slow_mo_ms=slow_mo_ms,
        tracer=tracer,
        base=base,
    )

    if tracer:
        tracer.log("auth probe after interactive login (persistent profile)")
    browser, context, page = await _open_persistent_session(
        playwright,
        service,
        base=base,
        headless=headless,
        slow_mo_ms=slow_mo_ms,
        tracer=tracer,
    )

    if not await probe_authentication(page, service, login_markers):
        if tracer:
            tracer.log("auth probe failed after interactive login")
        await _close_context(context)
        raise AuthenticationError(
            f"Authentication failed for '{service.name}' after interactive login"
        )

    if tracer:
        tracer.log("auth probe succeeded after interactive login")
    return AuthenticatedSession(
        browser=browser, context=context, page=page, service=service
    )


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

    When ``service.user_data_dir`` is set, AID opens that browser profile
    directly (required for OpenAI-style Auth0 sessions that do not fit in
    storage_state JSON).
    """
    if service.user_data_dir:
        return await _authenticate_with_profile(
            playwright,
            service,
            login_markers,
            base=base,
            allow_interactive=allow_interactive,
            headed=headed,
            slow_mo_ms=slow_mo_ms,
            tracer=tracer,
        )
    return await _authenticate_with_storage_state(
        playwright,
        service,
        login_markers,
        base=base,
        allow_interactive=allow_interactive,
        headed=headed,
        slow_mo_ms=slow_mo_ms,
        tracer=tracer,
    )
