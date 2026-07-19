"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from aid.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yml"


def test_load_example_config_enabled_services_only():
    config = load_config(
        EXAMPLE,
        known_services=frozenset(
            {
                "aws",
                "heroku",
                "openai",
                "google_ads",
                "google_cloud",
                "ing-zoomit",
            }
        ),
        known_api_services=frozenset({"chargebee"}),
    )
    assert [s.name for s in config.services] == [
        "aws",
        "heroku",
        "google_cloud",
        "openai",
        "google_ads",
    ]
    assert config.api_services == []
    assert config.download_format == "%Y-%m-invoice.pdf"
    assert "Log in" in config.login_markers
    by_name = {s.name: s for s in config.services}
    assert by_name["aws"].dashboard_marker == "AWS estimated bill summary"
    assert by_name["heroku"].dashboard_marker == "Billing Information"
    assert by_name["google_cloud"].dashboard_marker == "Invoices"
    assert by_name["openai"].dashboard_marker == "Billing history"
    assert by_name["openai"].user_data_dir == ".aid/chrome-openai"
    assert by_name["openai"].browser_channel == "chrome"
    assert by_name["google_ads"].dashboard_marker == "Billing activity"


def test_user_data_dir_optional(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  openai:
    relative_date_range: last_quarter
    output_directory: invoices/openai
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
    user_data_dir: .aid/chrome-openai
    browser_channel: chrome
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(path, known_services=frozenset({"openai"}))
    assert config.services[0].user_data_dir == ".aid/chrome-openai"
    assert config.services[0].browser_channel == "chrome"


def test_dashboard_marker_optional(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(path, known_services=frozenset({"aws"}))
    assert config.services[0].dashboard_marker is None


def test_dashboard_marker_empty_rejected(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
    dashboard_marker: "   "
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="dashboard_marker"):
        load_config(path, known_services=frozenset({"aws"}))


def test_enabled_false_skipped(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    enabled: false
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
  heroku:
    relative_date_range: last_quarter
    output_directory: invoices/heroku
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(path, known_services=frozenset({"aws", "heroku"}))
    assert [s.name for s in config.services] == ["heroku"]


def test_enabled_defaults_to_true(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
login_markers: []
download:
  format: "%Y-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(path, known_services=frozenset({"aws"}))
    assert len(config.services) == 1


def test_unknown_date_range(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_month
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unsupported relative_date_range"):
        load_config(path, known_services=frozenset({"aws"}))


def test_missing_required_key(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="dashboard_url"):
        load_config(path, known_services=frozenset({"aws"}))


def test_enabled_unknown_service(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  some_future_vendor:
    enabled: true
    relative_date_range: last_quarter
    output_directory: invoices/other
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="no service module is registered"):
        load_config(path, known_services=frozenset({"aws", "heroku"}))


def test_load_api_services(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
api_services:
  chargebee:
    tenant: acme
    api_key: secret-key
    output_directory: invoices/chargebee
    relative_date_range: last_quarter
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(
        path,
        known_services=frozenset({"aws"}),
        known_api_services=frozenset({"chargebee"}),
    )
    assert [s.name for s in config.services] == ["aws"]
    assert len(config.api_services) == 1
    api = config.api_services[0]
    assert api.name == "chargebee"
    assert api.tenant == "acme"
    assert api.api_key == "secret-key"
    assert api.output_directory == "invoices/chargebee"
    assert api.relative_date_range == "last_quarter"


def test_api_service_enabled_false_skipped(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
api_services:
  chargebee:
    enabled: false
    tenant: acme
    api_key: secret-key
    output_directory: invoices/chargebee
    relative_date_range: last_quarter
  other:
    tenant: other
    api_key: key
    output_directory: invoices/other
    relative_date_range: last_quarter
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(
        path,
        known_api_services=frozenset({"chargebee", "other"}),
    )
    assert config.services == []
    assert [s.name for s in config.api_services] == ["other"]


def test_api_only_config(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
api_services:
  chargebee:
    tenant: acme
    api_key: secret-key
    output_directory: invoices/chargebee
    relative_date_range: last_quarter
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    config = load_config(path, known_api_services=frozenset({"chargebee"}))
    assert config.services == []
    assert [s.name for s in config.api_services] == ["chargebee"]


def test_enabled_unknown_api_service(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
api_services:
  future_billing:
    enabled: true
    output_directory: invoices/future
    relative_date_range: last_quarter
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="no service module is registered"):
        load_config(path, known_api_services=frozenset({"chargebee"}))


def test_no_enabled_services_rejected(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        """
services:
  aws:
    enabled: false
    relative_date_range: last_quarter
    output_directory: invoices/aws
    login_url: https://example.com/login
    dashboard_url: https://example.com/dash
api_services:
  chargebee:
    enabled: false
    tenant: acme
    api_key: secret
    output_directory: invoices/chargebee
    relative_date_range: last_quarter
login_markers: []
download:
  format: "%Y-%m-invoice.pdf"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="At least one enabled service"):
        load_config(
            path,
            known_services=frozenset({"aws"}),
            known_api_services=frozenset({"chargebee"}),
        )