"""Orchestrator: serial auth, parallel downloads, per-service isolation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Playwright

from aid.auth import AuthenticatedSession, AuthenticationError, authenticate, wait_for_enter
from aid.browser import start_playwright
from aid.config import AppConfig, ServiceConfig, load_config
from aid.dates import DateRange, resolve_date_range
from aid.debug import ActionTracer
from aid.services import get_service, known_service_names
from aid.setup.dirs import ensure_output_dir

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 10 * 60

PlaywrightFactory = Callable[[], Awaitable[Playwright]]


@dataclass(frozen=True)
class RunOptions:
    """Runtime options shared by ``aid run`` and ``aid debug``."""

    headed: bool = False
    slow_mo_ms: float = 0
    trace_actions: bool = False
    sequential: bool = False
    pause_before_close: bool = False


DEBUG_OPTIONS = RunOptions(
    headed=True,
    slow_mo_ms=250,
    trace_actions=True,
    sequential=True,
    pause_before_close=True,
)


@dataclass
class ServiceResult:
    service: str
    paths: list[Path] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class RunResult:
    results: list[ServiceResult]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)


async def _close_quietly(session: AuthenticatedSession | None) -> None:
    if session is None:
        return
    try:
        await session.browser.close()
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass


async def _stop_quietly(playwright: Playwright | None) -> None:
    if playwright is None:
        return
    try:
        await playwright.stop()
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass


async def _download_with_timeout(
    session: AuthenticatedSession,
    date_range: DateRange,
    output_directory: Path,
    name_format: str,
    *,
    timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    tracer: ActionTracer | None = None,
) -> list[Path]:
    module = get_service(session.service.name)
    if tracer:
        tracer.log(
            f"download phase "
            f"{date_range.start.isoformat()}..{date_range.end.isoformat()} "
            f"→ {output_directory}"
        )
    paths = await asyncio.wait_for(
        module.download(
            session.page,
            date_range.start,
            date_range.end,
            output_directory,
            name_format,
        ),
        timeout=timeout_seconds,
    )
    if tracer:
        tracer.log(
            "download phase finished → "
            + (", ".join(str(path) for path in paths) if paths else "(no files)")
        )
    return paths


async def _run_one_service(
    service: ServiceConfig,
    *,
    login_markers: list[str],
    name_format: str,
    base: Path | None,
    timeout_seconds: float,
    auth_lock: asyncio.Lock,
    authenticate_fn,
    playwright_factory: PlaywrightFactory,
    options: RunOptions,
) -> ServiceResult:
    """Run auth + download for one service on an isolated Playwright instance."""
    playwright: Playwright | None = None
    session: AuthenticatedSession | None = None
    tracer = ActionTracer(service.name) if options.trace_actions else None
    result: ServiceResult | None = None
    try:
        if tracer:
            tracer.log("service start")
        playwright = await playwright_factory()
        date_range = resolve_date_range(service.relative_date_range)

        # Serialize interactive auth across services; downloads may overlap
        # unless sequential debug mode is enabled.
        async with auth_lock:
            if tracer:
                tracer.log("authentication phase")
            session = await authenticate_fn(
                playwright,
                service,
                login_markers,
                base=base,
                headed=options.headed,
                slow_mo_ms=options.slow_mo_ms,
                tracer=tracer,
            )

        output_directory = ensure_output_dir(service.output_directory, base=base)
        paths = await _download_with_timeout(
            session,
            date_range,
            output_directory,
            name_format,
            timeout_seconds=timeout_seconds,
            tracer=tracer,
        )
        result = ServiceResult(service=service.name, paths=paths)
        return result
    except AuthenticationError as exc:
        if tracer:
            tracer.failure("authentication", exc)
        result = ServiceResult(service=service.name, error=str(exc))
        return result
    except TimeoutError:
        error = f"Download timed out after {timeout_seconds:.0f}s"
        if tracer:
            tracer.log(f"✗ download phase → {error}")
        result = ServiceResult(service=service.name, error=error)
        return result
    except Exception as exc:  # noqa: BLE001 — isolate per-service failures
        logger.exception("Service '%s' failed", service.name)
        if tracer:
            tracer.failure("service", exc)
        result = ServiceResult(service=service.name, error=str(exc))
        return result
    finally:
        if options.pause_before_close and session is not None:
            status = "ok" if result is not None and result.ok else "failed"
            await wait_for_enter(
                prompt=(
                    f"[aid:{service.name}] Service {status}. "
                    "Inspect the browser if needed, then press Enter to close it."
                )
            )
        if tracer:
            tracer.log("service cleanup")
        await _close_quietly(session)
        await _stop_quietly(playwright)


async def run_orchestrator(
    config: AppConfig,
    *,
    base: Path | None = None,
    download_timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    authenticate_fn=authenticate,
    playwright_factory: PlaywrightFactory | None = None,
    options: RunOptions | None = None,
) -> RunResult:
    """Run each service in isolation; authenticate serially, download in parallel.

    Every service gets its own Playwright instance so a crash or browser teardown
    in one service cannot abort interactive auth or downloads in another.
    An auth lock keeps interactive login prompts sequential and in config order.

    When ``options.sequential`` is True (debug mode), services run one after
    another so headed browsers and console traces stay easy to follow.
    """
    run_options = options or RunOptions()
    factory = playwright_factory or start_playwright
    auth_lock = asyncio.Lock()

    async def run_service(service: ServiceConfig) -> ServiceResult:
        return await _run_one_service(
            service,
            login_markers=config.login_markers,
            name_format=config.download_format,
            base=base,
            timeout_seconds=download_timeout_seconds,
            auth_lock=auth_lock,
            authenticate_fn=authenticate_fn,
            playwright_factory=factory,
            options=run_options,
        )

    if run_options.sequential:
        results = [await run_service(service) for service in config.services]
        return RunResult(results=results)

    tasks = [
        asyncio.create_task(run_service(service), name=f"aid:{service.name}")
        for service in config.services
    ]
    results = await asyncio.gather(*tasks) if tasks else []
    return RunResult(results=list(results))


async def run_from_path(
    config_path: Path | str,
    *,
    base: Path | None = None,
    options: RunOptions | None = None,
) -> RunResult:
    config = load_config(config_path, known_services=known_service_names())
    return await run_orchestrator(config, base=base, options=options)
