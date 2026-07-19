# OpenAI

Open AI is a GUI-based service.

Open AI issues invoices any time it's time to top up the account. To get all invoices for a period of time, the module script must grab all invoices for that period of time. The invoices must be given a suffix of the invoice number. If the file names match completely, the invoices are overwritten.

Every invoice has a View button that leads to a pop up form with two buttons - Download Invoice and Download Receipt.
The Download Invoice button downloads the invoice PDF.

Interactive login often fails Google CAPTCHA inside Playwright's Chromium. See [login.md](./login.md) for the workaround.
