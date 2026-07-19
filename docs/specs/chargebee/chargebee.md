# Chargebee e-invoice download

Chargebee is an API-based service.

Chargebee is an invoicing system that allows downloading e-invoices via API rather than a GUI.

Configuration uses `tenant` (Chargebee site name) and `api_key` under `api_services.chargebee`.

Chargebee provides an API to [list invoices](https://apidocs.chargebee.com/docs/api/invoices/list-invoices) and [download e-invoices](https://apidocs.chargebee.com/docs/api/invoices/download-e-invoice).

AID lists invoices whose document date falls in the configured date range, then downloads the PDF from each successful e-invoice `downloads` entry (`mime_type` `application/pdf`). Invoices without an available e-invoice PDF are skipped.
