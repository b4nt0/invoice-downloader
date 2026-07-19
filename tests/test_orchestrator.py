"""Tests for orchestrator sequencing and isolation."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aid.auth import AuthenticatedSession, AuthenticationError
from aid.config import ApiServiceConfig, AppConfig, ServiceConfig
from aid.dates import DateRange
from aid.orchestrator import run_orchestrator
from aid.services import register_api_service, register_service


def _service(name: str) -> ServiceConfig:
    return ServiceConfig(
        name=name,
        relative_date_range="last_quarter",
        output_directory=f"invoices/{name}",
        login_url=f"https://example.com/{name}/login",
        dashboard_url=f"https://example.com/{name}/dash",
    )


def _api_service(name: str) -> ApiServiceConfig:
    return ApiServiceConfig(
        name=name,
        relative_date_range="last_quarter",
        output_directory=f"invoices/{name}",
        tenant="acme",
        api_key="test-key",
    )


def _config(*names: str, api_names: tuple[str, ...] = ()) -> AppConfig:
    return AppConfig(
        services=[_service(name) for name in names],
        api_services=[_api_service(name) for name in api_names],
        login_markers=["Sign in"],
        download_format="%Y-%m-invoice.pdf",
        path=Path("config.yml"),
    )


async def _fake_playwright_factory() -> MagicMock:
    pw = MagicMock()
    pw.stop = AsyncMock()
    return pw


class FakeModule:
    def __init__(self, events: list[str], name: str, delay: float = 0.05):
        self.events = events
        self.name = name
        self.delay = delay

    async def download(self, page, start, end, output_directory, name_format):
        self.events.append(f"download_start:{self.name}")
        await asyncio.sleep(self.delay)
        path = output_directory / f"{self.name}.pdf"
        path.write_bytes(b"%PDF")
        self.events.append(f"download_end:{self.name}")
        return [path]


@pytest.mark.asyncio
async def test_auth_order_and_parallel_downloads(tmp_path: Path, monkeypatch):
    events: list[str] = []
    register_service("aws", FakeModule(events, "aws", delay=0.1))
    register_service("heroku", FakeModule(events, "heroku", delay=0.01))

    async def fake_authenticate(playwright, service, login_markers, *, base=None, **_):
        events.append(f"auth_start:{service.name}")
        await asyncio.sleep(0.02)
        events.append(f"auth_end:{service.name}")
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    result = await run_orchestrator(
        _config("aws", "heroku"),
        base=tmp_path,
        authenticate_fn=fake_authenticate,
        playwright_factory=_fake_playwright_factory,
    )

    assert result.ok
    assert [r.service for r in result.results] == ["aws", "heroku"]

    # Auth is serial: aws finishes before heroku starts.
    assert events.index("auth_end:aws") < events.index("auth_start:heroku")
    # Downloads overlap: heroku auth can finish and heroku download can start
    # before aws download finishes.
    assert events.index("auth_start:heroku") < events.index("download_end:aws")
    assert events.index("download_start:heroku") < events.index("download_end:aws")


@pytest.mark.asyncio
async def test_download_timeout(tmp_path: Path, monkeypatch):
    class SlowModule:
        async def download(self, page, start, end, output_directory, name_format):
            await asyncio.sleep(1.0)
            return []

    register_service("aws", SlowModule())

    async def fake_authenticate(playwright, service, login_markers, *, base=None, **_):
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    result = await run_orchestrator(
        _config("aws"),
        base=tmp_path,
        download_timeout_seconds=0.05,
        authenticate_fn=fake_authenticate,
        playwright_factory=_fake_playwright_factory,
    )
    assert not result.ok
    assert "timed out" in (result.results[0].error or "")


@pytest.mark.asyncio
async def test_skips_disabled_by_using_enabled_list_only(tmp_path: Path):
    """Orchestrator only sees services already filtered by load_config."""
    events: list[str] = []
    register_service("heroku", FakeModule(events, "heroku", delay=0.01))

    async def fake_authenticate(playwright, service, login_markers, *, base=None, **_):
        events.append(service.name)
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    result = await run_orchestrator(
        _config("heroku"),
        base=tmp_path,
        authenticate_fn=fake_authenticate,
        playwright_factory=_fake_playwright_factory,
    )
    assert result.ok
    assert events == ["heroku", "download_start:heroku", "download_end:heroku"]


@pytest.mark.asyncio
async def test_auth_failure_recorded(tmp_path: Path):
    async def fail_auth(*_args, **_kwargs):
        raise AuthenticationError("nope")

    result = await run_orchestrator(
        _config("aws"),
        base=tmp_path,
        authenticate_fn=fail_auth,
        playwright_factory=_fake_playwright_factory,
    )
    assert not result.ok
    assert result.results[0].error == "nope"


@pytest.mark.asyncio
async def test_debug_options_run_sequentially_and_pause(tmp_path: Path, monkeypatch):
    events: list[str] = []
    register_service("aws", FakeModule(events, "aws", delay=0.01))
    register_service("heroku", FakeModule(events, "heroku", delay=0.01))

    async def fake_authenticate(
        playwright, service, login_markers, *, base=None, headed=False, **_
    ):
        events.append(f"auth:{service.name}:headed={headed}")
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    pauses: list[str] = []

    async def fake_enter(*, prompt=None):
        pauses.append(prompt or "")

    monkeypatch.setattr("aid.orchestrator.wait_for_enter", fake_enter)
    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    from aid.orchestrator import RunOptions

    result = await run_orchestrator(
        _config("aws", "heroku"),
        base=tmp_path,
        authenticate_fn=fake_authenticate,
        playwright_factory=_fake_playwright_factory,
        options=RunOptions(
            headed=True,
            trace_actions=False,
            sequential=True,
            pause_before_close=True,
        ),
    )
    assert result.ok
    assert events.index("auth:aws:headed=True") < events.index("auth:heroku:headed=True")
    assert events.index("download_end:aws") < events.index("auth:heroku:headed=True")
    assert len(pauses) == 2


@pytest.mark.asyncio
async def test_download_failure_does_not_break_other_service(tmp_path: Path, monkeypatch):
    events: list[str] = []

    class FailingAws:
        async def download(self, page, start, end, output_directory, name_format):
            events.append("download_start:aws")
            raise RuntimeError("aws boom")

    register_service("aws", FailingAws())
    register_service("heroku", FakeModule(events, "heroku", delay=0.05))

    async def fake_authenticate(playwright, service, login_markers, *, base=None, **_):
        events.append(f"auth_start:{service.name}")
        await asyncio.sleep(0.01)
        events.append(f"auth_end:{service.name}")
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    playwrights: list[MagicMock] = []

    async def tracking_factory() -> MagicMock:
        pw = await _fake_playwright_factory()
        playwrights.append(pw)
        return pw

    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    result = await run_orchestrator(
        _config("aws", "heroku"),
        base=tmp_path,
        authenticate_fn=fake_authenticate,
        playwright_factory=tracking_factory,
    )

    assert [r.service for r in result.results] == ["aws", "heroku"]
    assert not result.results[0].ok
    assert "aws boom" in (result.results[0].error or "")
    assert result.results[1].ok
    assert "download_end:heroku" in events
    # Each service used an isolated Playwright instance.
    assert len(playwrights) == 2
    assert all(pw.stop.await_count == 1 for pw in playwrights)


class FakeApiModule:
    def __init__(self, events: list[str], name: str, delay: float = 0.05):
        self.events = events
        self.name = name
        self.delay = delay

    async def download(
        self,
        start,
        end,
        output_directory,
        name_format,
        *,
        tenant,
        api_key,
    ):
        self.events.append(f"api_download_start:{self.name}")
        self.events.append(f"api_creds:{tenant}:{api_key}")
        await asyncio.sleep(self.delay)
        path = output_directory / f"{self.name}.pdf"
        path.write_bytes(b"%PDF")
        self.events.append(f"api_download_end:{self.name}")
        return [path]


@pytest.mark.asyncio
async def test_api_service_runs_without_playwright(tmp_path: Path, monkeypatch):
    events: list[str] = []
    register_api_service("chargebee", FakeApiModule(events, "chargebee", delay=0.01))

    playwright_calls = 0

    async def tracking_factory() -> MagicMock:
        nonlocal playwright_calls
        playwright_calls += 1
        return await _fake_playwright_factory()

    async def fail_auth(*_args, **_kwargs):
        raise AssertionError("GUI auth should not run for API-only config")

    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    result = await run_orchestrator(
        _config(api_names=("chargebee",)),
        base=tmp_path,
        authenticate_fn=fail_auth,
        playwright_factory=tracking_factory,
    )

    assert result.ok
    assert [r.service for r in result.results] == ["chargebee"]
    assert playwright_calls == 0
    assert events == [
        "api_download_start:chargebee",
        "api_creds:acme:test-key",
        "api_download_end:chargebee",
    ]


@pytest.mark.asyncio
async def test_api_service_runs_alongside_gui(tmp_path: Path, monkeypatch):
    events: list[str] = []
    register_service("heroku", FakeModule(events, "heroku", delay=0.05))
    register_api_service("chargebee", FakeApiModule(events, "chargebee", delay=0.01))

    async def fake_authenticate(playwright, service, login_markers, *, base=None, **_):
        events.append(f"auth_start:{service.name}")
        await asyncio.sleep(0.02)
        events.append(f"auth_end:{service.name}")
        browser = AsyncMock()
        browser.close = AsyncMock()
        return AuthenticatedSession(
            browser=browser,
            context=AsyncMock(),
            page=AsyncMock(),
            service=service,
        )

    monkeypatch.setattr(
        "aid.orchestrator.resolve_date_range",
        lambda relative: DateRange(date(2026, 4, 1), date(2026, 6, 30)),
    )

    result = await run_orchestrator(
        _config("heroku", api_names=("chargebee",)),
        base=tmp_path,
        authenticate_fn=fake_authenticate,
        playwright_factory=_fake_playwright_factory,
    )

    assert result.ok
    assert {r.service for r in result.results} == {"heroku", "chargebee"}
    # API download can start before GUI auth finishes.
    assert events.index("api_download_start:chargebee") < events.index("auth_end:heroku")
    assert "api_download_end:chargebee" in events
    assert "download_end:heroku" in events
