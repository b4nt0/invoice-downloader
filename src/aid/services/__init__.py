"""Registry mapping config service keys to modules."""

from __future__ import annotations

from aid.services.aws import AwsService
from aid.services.base import ServiceModule
from aid.services.google_ads import GoogleAdsService
from aid.services.heroku import HerokuService
from aid.services.openai import OpenAIService

_REGISTRY: dict[str, ServiceModule] = {
    "aws": AwsService(),
    "heroku": HerokuService(),
    "google_ads": GoogleAdsService(),
    "openai": OpenAIService(),
}


def known_service_names() -> frozenset[str]:
    return frozenset(_REGISTRY)


def get_service(name: str) -> ServiceModule:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"No service module registered for '{name}'") from exc


def register_service(name: str, module: ServiceModule) -> None:
    """Register or replace a service module (used by tests)."""
    _REGISTRY[name] = module
