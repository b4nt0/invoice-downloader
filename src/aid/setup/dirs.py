"""Ensure invoice output directories exist."""

from __future__ import annotations

from pathlib import Path

from aid.config import AppConfig, ServiceConfig


def ensure_output_dir(output_directory: str | Path, *, base: Path | None = None) -> Path:
    """Create *output_directory* (relative to *base* or cwd) and return it."""
    path = Path(output_directory)
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def ensure_output_dirs(
    config: AppConfig | list[ServiceConfig],
    *,
    base: Path | None = None,
) -> list[Path]:
    """Create output directories for every enabled service."""
    services = config.services if isinstance(config, AppConfig) else config
    return [
        ensure_output_dir(service.output_directory, base=base) for service in services
    ]
