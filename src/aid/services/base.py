"""Service module protocol."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol

from playwright.async_api import Page


class ServiceModule(Protocol):
    """Contract implemented by each vendor GUI service module."""

    async def download(
        self,
        page: Page,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
    ) -> list[Path]:
        """Download invoices in ``[start, end]`` and return saved PDF paths."""
        ...


class ApiServiceModule(Protocol):
    """Contract implemented by each vendor API service module."""

    async def download(
        self,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
        *,
        tenant: str | None,
        api_key: str | None,
    ) -> list[Path]:
        """Download invoices in ``[start, end]`` and return saved PDF paths."""
        ...
