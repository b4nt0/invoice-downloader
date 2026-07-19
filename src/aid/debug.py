"""Centralized Playwright action tracing for debug mode."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from playwright.async_api import Locator, Page

# Page / Locator methods that represent meaningful automation steps.
_PAGE_METHODS = frozenset(
    {
        "goto",
        "click",
        "fill",
        "press",
        "check",
        "uncheck",
        "select_option",
        "hover",
        "wait_for_selector",
        "wait_for_load_state",
        "wait_for_url",
        "wait_for_function",
        "wait_for_timeout",
        "title",
        "content",
        "reload",
        "go_back",
        "go_forward",
        "set_content",
        "evaluate",
        "expect_download",
        "expect_navigation",
        "expect_popup",
        "expect_file_chooser",
    }
)

_LOCATOR_METHODS = frozenset(
    {
        "click",
        "fill",
        "press",
        "check",
        "uncheck",
        "select_option",
        "hover",
        "count",
        "inner_text",
        "text_content",
        "get_attribute",
        "is_visible",
        "is_enabled",
        "wait_for",
        "all_inner_texts",
        "all_text_contents",
        "element_handle",
        "screenshot",
    }
)

_LOCATOR_FACTORIES = frozenset(
    {
        "locator",
        "get_by_role",
        "get_by_text",
        "get_by_label",
        "get_by_placeholder",
        "get_by_alt_text",
        "get_by_title",
        "get_by_test_id",
    }
)

_LOCATOR_CHAIN = frozenset({"first", "last", "nth", "locator", "filter", "and_", "or_"})


def _fmt_arg(value: Any) -> str:
    text = repr(value)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _fmt_call(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [_fmt_arg(arg) for arg in args]
    parts.extend(f"{key}={_fmt_arg(value)}" for key, value in kwargs.items())
    return f"{name}({', '.join(parts)})"


def _fmt_result(result: Any) -> str:
    if result is None:
        return "None"
    if isinstance(result, (str, int, float, bool)):
        return _fmt_arg(result)
    type_name = type(result).__name__
    return f"<{type_name}>"


class ActionTracer:
    """Prints attempted Playwright actions and their outcomes."""

    def __init__(
        self,
        service: str,
        *,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        self.service = service
        self._sink = sink or (lambda message: print(message, flush=True))

    def log(self, message: str) -> None:
        self._sink(f"[aid:{self.service}] {message}")

    def attempt(self, action: str) -> None:
        self.log(f"→ {action}")

    def success(self, action: str, detail: str = "ok") -> None:
        self.log(f"✓ {action} → {detail}")

    def failure(self, action: str, error: BaseException) -> None:
        self.log(f"✗ {action} → {type(error).__name__}: {error}")

    def instrument_page(self, page: Page) -> Page:
        """Return a page proxy that logs automation calls."""
        self._attach_navigation_hooks(page)
        return InstrumentedPage(page, self)  # type: ignore[return-value]

    def _attach_navigation_hooks(self, page: Page) -> None:
        def on_nav(frame) -> None:  # noqa: ANN001
            if frame == page.main_frame:
                self.log(f"navigated → {frame.url}")

        page.on("framenavigated", on_nav)
        page.on("download", lambda download: self.log(f"download event → {download.url}"))
        page.on("crash", lambda: self.log("page crashed"))


class InstrumentedAsyncCM:
    def __init__(self, cm: Any, tracer: ActionTracer, label: str) -> None:
        self._cm = cm
        self._tracer = tracer
        self._label = label

    async def __aenter__(self) -> Any:
        self._tracer.attempt(self._label)
        try:
            result = await self._cm.__aenter__()
            self._tracer.success(self._label, _fmt_result(result))
            return result
        except Exception as exc:
            self._tracer.failure(self._label, exc)
            raise

    async def __aexit__(self, exc_type, exc, tb) -> Any:  # noqa: ANN001
        return await self._cm.__aexit__(exc_type, exc, tb)


class InstrumentedLocator:
    def __init__(self, locator: Locator, tracer: ActionTracer, path: str) -> None:
        self._locator = locator
        self._tracer = tracer
        self._path = path

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._locator, name)

        if name in _LOCATOR_CHAIN and not callable(attr):
            # Properties like .first / .last
            child = attr
            child_path = f"{self._path}.{name}"
            self._tracer.log(f"resolve {child_path}")
            return InstrumentedLocator(child, self._tracer, child_path)

        if name in _LOCATOR_CHAIN and callable(attr):

            def chain(*args: Any, **kwargs: Any) -> InstrumentedLocator:
                child_path = f"{self._path}.{_fmt_call(name, args, kwargs)}"
                self._tracer.log(f"resolve {child_path}")
                return InstrumentedLocator(attr(*args, **kwargs), self._tracer, child_path)

            return chain

        if name in _LOCATOR_METHODS and callable(attr):
            return self._wrap_call(name, attr)

        return attr

    def _wrap_call(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        label_prefix = f"{self._path}.{name}"

        if inspect.iscoroutinefunction(fn):

            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                label = _fmt_call(label_prefix, args, kwargs)
                self._tracer.attempt(label)
                try:
                    result = await fn(*args, **kwargs)
                    self._tracer.success(label, _fmt_result(result))
                    return result
                except Exception as exc:
                    self._tracer.failure(label, exc)
                    raise

            return async_wrapper

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            label = _fmt_call(label_prefix, args, kwargs)
            self._tracer.attempt(label)
            try:
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):

                    async def awaited() -> Any:
                        try:
                            value = await result
                            self._tracer.success(label, _fmt_result(value))
                            return value
                        except Exception as exc:
                            self._tracer.failure(label, exc)
                            raise

                    return awaited()
                self._tracer.success(label, _fmt_result(result))
                return result
            except Exception as exc:
                self._tracer.failure(label, exc)
                raise

        return sync_wrapper


class InstrumentedPage:
    def __init__(self, page: Page, tracer: ActionTracer) -> None:
        self._page = page
        self._tracer = tracer

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._page, name)

        if name in _LOCATOR_FACTORIES and callable(attr):

            def factory(*args: Any, **kwargs: Any) -> InstrumentedLocator:
                path = _fmt_call(name, args, kwargs)
                self._tracer.log(f"resolve {path}")
                return InstrumentedLocator(attr(*args, **kwargs), self._tracer, path)

            return factory

        if name in _PAGE_METHODS and callable(attr):
            return self._wrap_call(name, attr)

        return attr

    @property
    def url(self) -> str:
        return self._page.url

    def _wrap_call(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        if name.startswith("expect_"):

            def expect_wrapper(*args: Any, **kwargs: Any) -> InstrumentedAsyncCM:
                label = _fmt_call(f"page.{name}", args, kwargs)
                return InstrumentedAsyncCM(fn(*args, **kwargs), self._tracer, label)

            return expect_wrapper

        if inspect.iscoroutinefunction(fn):

            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                label = _fmt_call(f"page.{name}", args, kwargs)
                self._tracer.attempt(label)
                try:
                    result = await fn(*args, **kwargs)
                    self._tracer.success(label, _fmt_result(result))
                    return result
                except Exception as exc:
                    self._tracer.failure(label, exc)
                    raise

            return async_wrapper

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            label = _fmt_call(f"page.{name}", args, kwargs)
            self._tracer.attempt(label)
            try:
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):

                    async def awaited() -> Any:
                        try:
                            value = await result
                            self._tracer.success(label, _fmt_result(value))
                            return value
                        except Exception as exc:
                            self._tracer.failure(label, exc)
                            raise

                    return awaited()
                self._tracer.success(label, _fmt_result(result))
                return result
            except Exception as exc:
                self._tracer.failure(label, exc)
                raise

        return sync_wrapper
