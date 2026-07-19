"""Tests for Chargebee API service helpers and download flow."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aid.services.chargebee import (
    ChargebeeError,
    ChargebeeService,
    date_range_to_epoch_bounds,
    download_einvoice_pdf,
    list_invoices,
    parse_invoice_entries,
    select_pdf_download_url,
)


def test_date_range_to_epoch_bounds_inclusive_utc():
    after, before = date_range_to_epoch_bounds(date(2026, 4, 1), date(2026, 6, 30))
    assert after == 1775001600  # 2026-04-01 00:00:00 UTC
    assert before == 1782863999  # 2026-06-30 23:59:59 UTC


def test_parse_invoice_entries():
    payload = {
        "list": [
            {"invoice": {"id": "inv_1", "date": 1775001600}},
            {"invoice": {"id": "inv_2", "date": 1777680000}},
            {"invoice": {"id": "", "date": 1775001600}},
            {"not_invoice": {}},
        ]
    }
    invoices = parse_invoice_entries(payload)
    assert [(i.id, i.invoice_date) for i in invoices] == [
        ("inv_1", date(2026, 4, 1)),
        ("inv_2", date(2026, 5, 2)),
    ]


def test_select_pdf_download_url():
    payload = {
        "downloads": [
            {
                "mime_type": "application/xml",
                "download_url": "https://example.com/xml",
            },
            {
                "mime_type": "application/pdf",
                "download_url": "https://example.com/pdf",
            },
        ]
    }
    assert select_pdf_download_url(payload) == "https://example.com/pdf"
    assert select_pdf_download_url({"downloads": []}) is None


def _response(status_code: int, *, json_data=None, content: bytes = b"", text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.content = content
    response.json.return_value = json_data
    return response


def test_list_invoices_paginates():
    calls: list[dict] = []

    def request_fn(method, url, *, auth=None, params=None, timeout=None):
        calls.append({"method": method, "url": url, "auth": auth, "params": params})
        if params and params.get("offset") == "page2":
            return _response(
                200,
                json_data={
                    "list": [{"invoice": {"id": "inv_2", "date": 1777680000}}],
                },
            )
        return _response(
            200,
            json_data={
                "list": [{"invoice": {"id": "inv_1", "date": 1775001600}}],
                "next_offset": "page2",
            },
        )

    invoices = list_invoices(
        tenant="acme",
        api_key="secret",
        start=date(2026, 4, 1),
        end=date(2026, 6, 30),
        request_fn=request_fn,
    )
    assert [i.id for i in invoices] == ["inv_1", "inv_2"]
    assert len(calls) == 2
    assert calls[0]["auth"] == ("secret", "")
    assert calls[0]["params"]["date[after]"] == 1775001600 - 1
    assert calls[0]["params"]["date[before]"] == 1782863999 + 1
    assert calls[1]["params"]["offset"] == "page2"


def test_list_invoices_auth_failure():
    def request_fn(*_args, **_kwargs):
        return _response(401, text="unauthorized")

    with pytest.raises(ChargebeeError, match="authentication failed"):
        list_invoices(
            tenant="acme",
            api_key="bad",
            start=date(2026, 4, 1),
            end=date(2026, 6, 30),
            request_fn=request_fn,
        )


def test_download_einvoice_pdf_success_and_skip():
    def request_fn(method, url, *, auth=None, params=None, timeout=None):
        if url.endswith("/download_einvoice"):
            if "missing" in url:
                return _response(404, text="not found")
            return _response(
                200,
                json_data={
                    "downloads": [
                        {
                            "mime_type": "application/pdf",
                            "download_url": "https://cdn.example.com/inv.pdf",
                        }
                    ]
                },
            )
        if url == "https://cdn.example.com/inv.pdf":
            return _response(200, content=b"%PDF-1.4")
        raise AssertionError(f"unexpected url {url}")

    pdf = download_einvoice_pdf(
        tenant="acme",
        api_key="secret",
        invoice_id="inv_1",
        request_fn=request_fn,
    )
    assert pdf == b"%PDF-1.4"

    skipped = download_einvoice_pdf(
        tenant="acme",
        api_key="secret",
        invoice_id="missing",
        request_fn=request_fn,
    )
    assert skipped is None


@pytest.mark.asyncio
async def test_chargebee_service_download(tmp_path: Path):
    def request_fn(method, url, *, auth=None, params=None, timeout=None):
        if url.endswith("/invoices") and "download_einvoice" not in url:
            return _response(
                200,
                json_data={
                    "list": [
                        {"invoice": {"id": "inv_ok", "date": 1775001600}},
                        {"invoice": {"id": "inv_skip", "date": 1777680000}},
                    ]
                },
            )
        if url.endswith("/inv_ok/download_einvoice"):
            return _response(
                200,
                json_data={
                    "downloads": [
                        {
                            "mime_type": "application/pdf",
                            "download_url": "https://cdn.example.com/ok.pdf",
                        }
                    ]
                },
            )
        if url.endswith("/inv_skip/download_einvoice"):
            return _response(404, text="no e-invoice")
        if url == "https://cdn.example.com/ok.pdf":
            return _response(200, content=b"%PDF-ok")
        raise AssertionError(f"unexpected url {url}")

    service = ChargebeeService(request_fn=request_fn)
    paths = await service.download(
        date(2026, 4, 1),
        date(2026, 6, 30),
        tmp_path,
        "%Y-%m-invoice.pdf",
        tenant="acme",
        api_key="secret",
    )
    assert len(paths) == 1
    assert paths[0].name == "2026-04-invoice.pdf"
    assert paths[0].read_bytes() == b"%PDF-ok"


@pytest.mark.asyncio
async def test_chargebee_service_requires_credentials(tmp_path: Path):
    service = ChargebeeService()
    with pytest.raises(ChargebeeError, match="tenant"):
        await service.download(
            date(2026, 4, 1),
            date(2026, 6, 30),
            tmp_path,
            "%Y-%m-invoice.pdf",
            tenant=None,
            api_key="secret",
        )
    with pytest.raises(ChargebeeError, match="api_key"):
        await service.download(
            date(2026, 4, 1),
            date(2026, 6, 30),
            tmp_path,
            "%Y-%m-invoice.pdf",
            tenant="acme",
            api_key=None,
        )
