"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

import aid.services as services
from aid.services.aws import AwsService
from aid.services.chargebee import ChargebeeService
from aid.services.google_ads import GoogleAdsService
from aid.services.google_cloud import GoogleCloudService
from aid.services.heroku import HerokuService
from aid.services.ing_zoomit import IngZoomitService
from aid.services.openai import OpenAIService


@pytest.fixture(autouse=True)
def restore_service_registry():
    """Keep service registries stable across tests that call register_*."""
    original = dict(services._REGISTRY)
    original_api = dict(services._API_REGISTRY)
    yield
    services._REGISTRY.clear()
    services._REGISTRY.update(original)
    services._REGISTRY.setdefault("aws", AwsService())
    services._REGISTRY.setdefault("heroku", HerokuService())
    services._REGISTRY.setdefault("google_ads", GoogleAdsService())
    services._REGISTRY.setdefault("google_cloud", GoogleCloudService())
    services._REGISTRY.setdefault("openai", OpenAIService())
    services._REGISTRY.setdefault("ing-zoomit", IngZoomitService())
    services._API_REGISTRY.clear()
    services._API_REGISTRY.update(original_api)
    services._API_REGISTRY.setdefault("chargebee", ChargebeeService())
