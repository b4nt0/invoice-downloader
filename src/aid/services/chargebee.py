"""Chargebee API-based e-invoice downloader."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import requests

from aid.naming import format_invoice_name, unique_path

logger = logging.getLogger(__name__)

RequestFn = Callable[..., requests.Response]


class ChargebeeError(RuntimeError):
    """Raised when Chargebee credentials or list requests fail."""


@dataclass(frozen=True)
class ChargebeeInvoice:
    id: str
    invoice_date: date


def date_range_to_epoch_bounds(start: date, end: date) -> tuple[int, int]:
    """Return inclusive UTC Unix-second bounds for a calendar date range."""
    after = int(datetime.combine(start, time.min, tzinfo=timezone.utc).timestamp())
    before = int(datetime.combine(end, time(23, 59, 59), tzinfo=timezone.utc).timestamp())
    return after, before


def parse_invoice_entries(payload: dict[str, Any]) -> list[ChargebeeInvoice]:
    """Extract invoice id/date pairs from a Chargebee list response."""
    invoices: list[ChargebeeInvoice] = []
    for entry in payload.get("list") or []:
        if not isinstance(entry, dict):
            continue
        invoice = entry.get("invoice")
        if not isinstance(invoice, dict):
            continue
        invoice_id = invoice.get("id")
        raw_date = invoice.get("date")
        if not isinstance(invoice_id, str) or not invoice_id:
            continue
        if not isinstance(raw_date, (int, float)):
            continue
        invoice_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).date()
        invoices.append(ChargebeeInvoice(id=invoice_id, invoice_date=invoice_date))
    return invoices


def select_pdf_download_url(payload: dict[str, Any]) -> str | None:
    """Return the PDF download URL from a download_einvoice response, if any."""
    downloads = payload.get("downloads") or []
    for item in downloads:
        if not isinstance(item, dict):
            continue
        if item.get("mime_type") != "application/pdf":
            continue
        url = item.get("download_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _request(
    method: str,
    url: str,
    *,
    auth: tuple[str, str] | None = None,
    params: dict[str, Any] | None = None,
    request_fn: RequestFn | None = None,
) -> requests.Response:
    fn = request_fn or requests.request
    response = fn(method, url, auth=auth, params=params, timeout=60)
    return response


def list_invoices(
    *,
    tenant: str,
    api_key: str,
    start: date,
    end: date,
    request_fn: RequestFn | None = None,
) -> list[ChargebeeInvoice]:
    """List all invoices whose document date falls in ``[start, end]`` (UTC)."""
    after, before = date_range_to_epoch_bounds(start, end)
    base_url = f"https://{tenant}.chargebee.com/api/v2/invoices"
    auth = (api_key, "")
    invoices: list[ChargebeeInvoice] = []
    offset: str | None = None

    while True:
        params: dict[str, Any] = {
            "limit": 100,
            "date[after]": after - 1,
            "date[before]": before + 1,
            "sort_by[asc]": "date",
        }
        if offset is not None:
            params["offset"] = offset

        response = _request(
            "GET", base_url, auth=auth, params=params, request_fn=request_fn
        )
        if response.status_code in {401, 403}:
            raise ChargebeeError(
                f"Chargebee authentication failed (HTTP {response.status_code})"
            )
        if not response.ok:
            raise ChargebeeError(
                f"Chargebee list invoices failed (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            )

        payload = response.json()
        if not isinstance(payload, dict):
            raise ChargebeeError("Chargebee list invoices returned a non-object payload")

        invoices.extend(parse_invoice_entries(payload))
        next_offset = payload.get("next_offset")
        if not isinstance(next_offset, str) or not next_offset:
            break
        offset = next_offset

    return invoices


def download_einvoice_pdf(
    *,
    tenant: str,
    api_key: str,
    invoice_id: str,
    request_fn: RequestFn | None = None,
) -> bytes | None:
    """Download the e-invoice PDF for one invoice, or return None if unavailable."""
    url = (
        f"https://{tenant}.chargebee.com/api/v2/invoices/"
        f"{invoice_id}/download_einvoice"
    )
    response = _request(
        "GET", url, auth=(api_key, ""), request_fn=request_fn
    )
    if response.status_code in {401, 403}:
        raise ChargebeeError(
            f"Chargebee authentication failed (HTTP {response.status_code})"
        )
    if not response.ok:
        logger.info(
            "Skipping Chargebee invoice %s: download_einvoice HTTP %s",
            invoice_id,
            response.status_code,
        )
        return None

    payload = response.json()
    if not isinstance(payload, dict):
        logger.info(
            "Skipping Chargebee invoice %s: non-object download_einvoice payload",
            invoice_id,
        )
        return None

    pdf_url = select_pdf_download_url(payload)
    if pdf_url is None:
        logger.info(
            "Skipping Chargebee invoice %s: no PDF download URL",
            invoice_id,
        )
        return None

    pdf_response = _request("GET", pdf_url, request_fn=request_fn)
    if not pdf_response.ok:
        logger.info(
            "Skipping Chargebee invoice %s: PDF fetch HTTP %s",
            invoice_id,
            pdf_response.status_code,
        )
        return None
    return pdf_response.content


def _download_sync(
    start: date,
    end: date,
    output_directory: Path,
    name_format: str,
    *,
    tenant: str,
    api_key: str,
    request_fn: RequestFn | None = None,
) -> list[Path]:
    invoices = list_invoices(
        tenant=tenant,
        api_key=api_key,
        start=start,
        end=end,
        request_fn=request_fn,
    )
    saved: list[Path] = []
    for invoice in invoices:
        pdf_bytes = download_einvoice_pdf(
            tenant=tenant,
            api_key=api_key,
            invoice_id=invoice.id,
            request_fn=request_fn,
        )
        if pdf_bytes is None:
            continue
        filename = format_invoice_name(name_format, invoice.invoice_date)
        path = unique_path(output_directory, filename)
        path.write_bytes(pdf_bytes)
        saved.append(path)
    return saved


class ChargebeeService:
    """Download Chargebee e-invoice PDFs via the REST API."""

    def __init__(self, *, request_fn: RequestFn | None = None) -> None:
        self._request_fn = request_fn

    async def download(
        self,
        start: date,
        end: date,
        output_directory: Path,
        name_format: str,
        *,
        tenant: str | None,
        api_key: str | None,
    ) -> list[Path]:
        if not tenant or not tenant.strip():
            raise ChargebeeError("Chargebee requires a non-empty 'tenant'")
        if not api_key or not api_key.strip():
            raise ChargebeeError("Chargebee requires a non-empty 'api_key'")

        return await asyncio.to_thread(
            _download_sync,
            start,
            end,
            output_directory,
            name_format,
            tenant=tenant.strip(),
            api_key=api_key.strip(),
            request_fn=self._request_fn,
        )
