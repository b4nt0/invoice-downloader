"""Initialize a local config.yml from the example template."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


class InitConfigError(FileExistsError):
    """Raised when the target config already exists."""


def _example_config_text() -> str:
    """Load example config from the package or the repo root template."""
    package_root = Path(__file__).resolve().parents[3]
    example = package_root / "config.example.yml"
    if example.is_file():
        return example.read_text(encoding="utf-8")

    # Fallback for installed packages that ship the example as data.
    try:
        return (
            importlib.resources.files("aid")
            .joinpath("config.example.yml")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "Could not locate config.example.yml for aid init"
        ) from exc


def init_config(
    destination: Path | str = "config.yml",
    *,
    force: bool = False,
) -> Path:
    """Write ``config.yml`` from the example template if it does not exist."""
    target = Path(destination)
    if target.exists() and not force:
        raise InitConfigError(f"Config already exists: {target}")

    target.write_text(_example_config_text(), encoding="utf-8")
    return target.resolve()
