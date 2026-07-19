# ING Zoomit Credit Card Statements

ING Zoomit provides downloadable banking documents. This module targets **credit
card expenditure statements** only (subtitle `Credit card expenditure statement`),
not other Zoomit bills.

Configure under `services.ing-zoomit` (see `config.example.yml`):

- `dashboard_url`: `https://ebanking.ing.be/banking/orders/zoomit`
- `dashboard_marker`: `Zoomit`

Flow on the History list:

1. Find monthly groups (`June 2026`, …) overlapping the configured date range.
2. Within each month, select the credit card expenditure statement row
   (subtitle text lives in the `zoomit-document-item` open shadow root).
3. Expand the collapsible and click **View (PDF)**.
4. Save one PDF per month via the browser download event.
5. If View (PDF) closes the Zoomit tab (common with blob downloads), reopen
   History in the same session before the next month.

Other Zoomit documents (utility bills, etc.) are ignored.
