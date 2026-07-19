"""Tests for centralized debug action tracing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aid.debug import ActionTracer, InstrumentedPage


@pytest.mark.asyncio
async def test_instrumented_page_logs_goto_success_and_failure():
    lines: list[str] = []
    tracer = ActionTracer("aws", sink=lines.append)

    page = MagicMock()
    page.main_frame = object()
    page.on = MagicMock()
    page.goto = AsyncMock(side_effect=[None, RuntimeError("boom")])
    page.url = "https://example.com"

    instrumented = tracer.instrument_page(page)

    await instrumented.goto("https://example.com/dash")
    with pytest.raises(RuntimeError, match="boom"):
        await instrumented.goto("https://example.com/fail")

    joined = "\n".join(lines)
    assert "[aid:aws]" in joined
    assert "→ page.goto" in joined
    assert "✓ page.goto" in joined
    assert "✗ page.goto" in joined
    assert "boom" in joined


@pytest.mark.asyncio
async def test_instrumented_locator_logs_count():
    lines: list[str] = []
    tracer = ActionTracer("heroku", sink=lines.append)

    locator = MagicMock()
    locator.count = AsyncMock(return_value=3)

    page = MagicMock()
    page.main_frame = object()
    page.on = MagicMock()
    page.locator = MagicMock(return_value=locator)

    instrumented: InstrumentedPage = tracer.instrument_page(page)  # type: ignore[assignment]
    resolved = instrumented.locator("tbody tr")
    assert await resolved.count() == 3

    joined = "\n".join(lines)
    assert "resolve locator" in joined
    assert "→ locator" in joined and "count" in joined
    assert "✓" in joined and "3" in joined


def test_cli_debug_command_exists():
    from aid.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["debug", "-c", "config.yml"])
    assert args.command == "debug"
    assert args.config == "config.yml"
    assert args.slow_mo == 250
