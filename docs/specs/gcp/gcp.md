# Google Cloud

Google Cloud billing has a variable URL depending on the billing account number.
Set `dashboard_url` to
`https://console.cloud.google.com/billing/<BILLING_ACCOUNT_ID>/invoices`.

The invoice list lives in a Google Payments document-center iframe
(`iframe[name="billing-iframeIframe"]`). There is no per-row Download link.

To download an invoice:

1. Click the document number cell on a row (opens the invoice detail pop-up).
2. Open **Actions** → **Download**.
3. In the **Download documents** form, leave **PDF invoices** checked and click
   **Download**.

Prefer invoices/statements over tax-only memos. Download one PDF per month in
the configured date range.

`dashboard_marker` must be text from the Cloud Console shell (parent page), not
from inside the Payments iframe — for example `Invoices`.
