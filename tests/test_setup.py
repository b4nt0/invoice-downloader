"""Tests for setup helpers."""

from pathlib import Path

import pytest

from aid.config import ServiceConfig
from aid.setup.dirs import ensure_output_dir, ensure_output_dirs
from aid.setup.init_config import InitConfigError, init_config


def test_ensure_output_dir_creates_nested(tmp_path: Path):
    target = ensure_output_dir("invoices/aws", base=tmp_path)
    assert target.is_dir()
    assert target == (tmp_path / "invoices" / "aws").resolve()


def test_ensure_output_dirs_idempotent(tmp_path: Path):
    services = [
        ServiceConfig(
            name="aws",
            relative_date_range="last_quarter",
            output_directory="invoices/aws",
            login_url="https://example.com/login",
            dashboard_url="https://example.com/dash",
        )
    ]
    first = ensure_output_dirs(services, base=tmp_path)
    second = ensure_output_dirs(services, base=tmp_path)
    assert first == second
    assert first[0].is_dir()


def test_init_config_writes_example(tmp_path: Path):
    destination = tmp_path / "config.yml"
    path = init_config(destination)
    assert path == destination.resolve()
    assert "services:" in destination.read_text(encoding="utf-8")


def test_init_config_does_not_overwrite(tmp_path: Path):
    destination = tmp_path / "config.yml"
    destination.write_text("existing\n", encoding="utf-8")
    with pytest.raises(InitConfigError):
        init_config(destination)
    assert destination.read_text(encoding="utf-8") == "existing\n"
