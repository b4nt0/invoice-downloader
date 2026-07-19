"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from aid.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yml"


def test_load_example_config_enabled_services_only():
    config = load_config(EXAMPLE, known_services=frozenset({"aws", "heroku"}))
    assert [s.name for s in config.services] == ["aws", "heroku"]
    assert config.download_format == "%Y-%m-invoice.pdf"
    assert "Log in" in config.login_markers
    by_name = {s.name: s for s in config.services}
    assert by_name["aws"].dashboard_marker == "AWS estimated bill summary"
    assert by_name["heroku"].dashboard_marker == "Billing Information"


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
  google_cloud:
    enabled: true
    relative_date_range: last_quarter
    output_directory: invoices/gcp
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
