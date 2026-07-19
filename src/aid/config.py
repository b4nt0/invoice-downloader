"""Load and validate AID YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_DATE_RANGES = frozenset({"last_quarter"})


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    relative_date_range: str
    output_directory: str
    login_url: str
    dashboard_url: str
    dashboard_marker: str | None = None
    # When set, AID reuses this Chrome/Chromium profile instead of storage_state JSON.
    user_data_dir: str | None = None
    browser_channel: str | None = None


@dataclass(frozen=True)
class AppConfig:
    services: list[ServiceConfig]
    login_markers: list[str]
    download_format: str
    path: Path


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    if key not in data:
        raise ConfigError(f"Missing required key '{key}' in {context}")
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Key '{key}' in {context} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str, context: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Key '{key}' in {context} must be a non-empty string")
    return value.strip()


def load_config(
    path: Path | str,
    *,
    known_services: frozenset[str] | None = None,
) -> AppConfig:
    """Load YAML config and return enabled services only."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping")

    services_raw = raw.get("services")
    if not isinstance(services_raw, dict) or not services_raw:
        raise ConfigError("'services' must be a non-empty mapping")

    login_markers = raw.get("login_markers", [])
    if not isinstance(login_markers, list) or not all(
        isinstance(item, str) for item in login_markers
    ):
        raise ConfigError("'login_markers' must be a list of strings")

    download = raw.get("download")
    if not isinstance(download, dict):
        raise ConfigError("'download' must be a mapping")
    download_format = _require_str(download, "format", "download")

    enabled_services: list[ServiceConfig] = []
    for name, service_data in services_raw.items():
        if not isinstance(name, str):
            raise ConfigError("Service keys must be strings")
        if not isinstance(service_data, dict):
            raise ConfigError(f"Service '{name}' must be a mapping")

        enabled = service_data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"Service '{name}': 'enabled' must be a boolean")
        if not enabled:
            continue

        if known_services is not None and name not in known_services:
            raise ConfigError(
                f"Service '{name}' is enabled but no service module is registered"
            )

        relative_date_range = _require_str(
            service_data, "relative_date_range", f"service '{name}'"
        )
        if relative_date_range not in SUPPORTED_DATE_RANGES:
            raise ConfigError(
                f"Service '{name}': unsupported relative_date_range "
                f"'{relative_date_range}' (supported: "
                f"{', '.join(sorted(SUPPORTED_DATE_RANGES))})"
            )

        enabled_services.append(
            ServiceConfig(
                name=name,
                relative_date_range=relative_date_range,
                output_directory=_require_str(
                    service_data, "output_directory", f"service '{name}'"
                ),
                login_url=_require_str(service_data, "login_url", f"service '{name}'"),
                dashboard_url=_require_str(
                    service_data, "dashboard_url", f"service '{name}'"
                ),
                dashboard_marker=_optional_str(
                    service_data, "dashboard_marker", f"service '{name}'"
                ),
                user_data_dir=_optional_str(
                    service_data, "user_data_dir", f"service '{name}'"
                ),
                browser_channel=_optional_str(
                    service_data, "browser_channel", f"service '{name}'"
                ),
            )
        )

    return AppConfig(
        services=enabled_services,
        login_markers=list(login_markers),
        download_format=download_format,
        path=config_path.resolve(),
    )
