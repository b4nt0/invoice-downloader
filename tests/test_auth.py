"""Tests for authentication helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aid.auth import (
    AuthenticationError,
    authenticate,
    probe_authentication,
    title_has_login_marker,
    wait_for_interactive_completion,
)
from aid.browser import urls_match_ignoring_query
from aid.config import ServiceConfig


def _service() -> ServiceConfig:
    return ServiceConfig(
        name="aws",
        relative_date_range="last_quarter",
        output_directory="invoices/aws",
        login_url="https://example.com/login",
        dashboard_url="https://example.com/dashboard",
    )


def test_title_has_login_marker_case_insensitive():
    assert title_has_login_marker("Please Sign In", ["Log in", "Sign in"])
    assert not title_has_login_marker("Billing Dashboard", ["Log in", "Sign in"])


def test_urls_match_ignoring_query():
    assert urls_match_ignoring_query(
        "https://example.com/login?next=/x",
        "https://example.com/login",
    )
    assert not urls_match_ignoring_query(
        "https://example.com/dashboard",
        "https://example.com/login",
    )


@pytest.mark.asyncio
async def test_probe_success():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "https://example.com/dashboard"
    page.title = AsyncMock(return_value="Dashboard")
    assert await probe_authentication(page, _service(), ["Sign in"])


@pytest.mark.asyncio
async def test_probe_fails_on_login_url_redirect():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "https://example.com/login?redirect=%2Fdashboard"
    page.title = AsyncMock(return_value="Anything")
    assert not await probe_authentication(page, _service(), ["Sign in"])


@pytest.mark.asyncio
async def test_probe_fails_on_title_marker():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "https://example.com/sso"
    page.title = AsyncMock(return_value="AWS Sign in")
    assert not await probe_authentication(page, _service(), ["Sign in"])


@pytest.mark.asyncio
async def test_authenticate_aborts_after_one_interactive(tmp_path: Path, monkeypatch):
    service = _service()
    session_file = tmp_path / ".aid" / "sessions" / "aws.json"
    session_file.parent.mkdir(parents=True)
    session_file.write_text("{}", encoding="utf-8")

    interactive = AsyncMock()
    monkeypatch.setattr("aid.auth.interactive_login", interactive)
    monkeypatch.setattr("aid.auth.session_path", lambda name, base=None: session_file)

    browser = AsyncMock()
    browser.close = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "https://example.com/login"
    page.title = AsyncMock(return_value="Sign in")

    monkeypatch.setattr("aid.auth.launch_browser", AsyncMock(return_value=browser))
    monkeypatch.setattr("aid.auth.new_context", AsyncMock(return_value=context))
    monkeypatch.setattr("aid.auth.new_page", AsyncMock(return_value=page))
    monkeypatch.setattr("aid.auth.save_storage_state", AsyncMock())

    playwright = MagicMock()
    with pytest.raises(AuthenticationError, match="after interactive login"):
        await authenticate(playwright, service, ["Sign in"], base=tmp_path)

    assert interactive.await_count == 1


@pytest.mark.asyncio
async def test_authenticate_uses_saved_session(tmp_path: Path, monkeypatch):
    service = _service()
    session_file = tmp_path / ".aid" / "sessions" / "aws.json"
    session_file.parent.mkdir(parents=True)
    session_file.write_text("{}", encoding="utf-8")

    interactive = AsyncMock()
    monkeypatch.setattr("aid.auth.interactive_login", interactive)
    monkeypatch.setattr("aid.auth.session_path", lambda name, base=None: session_file)

    browser = AsyncMock()
    browser.close = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "https://example.com/dashboard"
    page.title = AsyncMock(return_value="Dashboard")

    monkeypatch.setattr("aid.auth.launch_browser", AsyncMock(return_value=browser))
    monkeypatch.setattr("aid.auth.new_context", AsyncMock(return_value=context))
    monkeypatch.setattr("aid.auth.new_page", AsyncMock(return_value=page))
    monkeypatch.setattr("aid.auth.save_storage_state", AsyncMock())

    session = await authenticate(MagicMock(), service, ["Sign in"], base=tmp_path)
    assert session.page is page
    interactive.assert_not_awaited()


@pytest.mark.asyncio
async def test_wait_for_interactive_completion_waits_for_enter():
    calls: list[str] = []

    async def press_enter(*, prompt=None):
        calls.append(prompt or "")

    await wait_for_interactive_completion(
        timeout_ms=5_000,
        wait_for_enter_fn=press_enter,
    )
    assert calls
    assert "press Enter" in calls[0]


@pytest.mark.asyncio
async def test_wait_for_interactive_completion_times_out():
    async def never_enter(*, prompt=None):
        await asyncio.sleep(10)

    with pytest.raises(AuthenticationError, match="Timed out"):
        await wait_for_interactive_completion(
            timeout_ms=50,
            wait_for_enter_fn=never_enter,
        )
