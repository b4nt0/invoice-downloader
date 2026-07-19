"""Registry mapping config service keys to modules."""

from __future__ import annotations

from aid.services.aws import AwsService
from aid.services.base import ApiServiceModule, ServiceModule
from aid.services.chargebee import ChargebeeService
from aid.services.google_ads import GoogleAdsService
from aid.services.google_cloud import GoogleCloudService
from aid.services.heroku import HerokuService
from aid.services.ing_zoomit import IngZoomitService
from aid.services.openai import OpenAIService

_REGISTRY: dict[str, ServiceModule] = {
    "aws": AwsService(),
    "heroku": HerokuService(),
    "google_ads": GoogleAdsService(),
    "google_cloud": GoogleCloudService(),
    "openai": OpenAIService(),
    "ing-zoomit": IngZoomitService(),
}

_API_REGISTRY: dict[str, ApiServiceModule] = {
    "chargebee": ChargebeeService(),
}


def known_service_names() -> frozenset[str]:
    return frozenset(_REGISTRY)


def known_api_service_names() -> frozenset[str]:
    return frozenset(_API_REGISTRY)


def get_service(name: str) -> ServiceModule:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"No service module registered for '{name}'") from exc


def get_api_service(name: str) -> ApiServiceModule:
    try:
        return _API_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"No API service module registered for '{name}'") from exc


def register_service(name: str, module: ServiceModule) -> None:
    """Register or replace a GUI service module (used by tests)."""
    _REGISTRY[name] = module


def register_api_service(name: str, module: ApiServiceModule) -> None:
    """Register or replace an API service module (used by tests)."""
    _API_REGISTRY[name] = module
