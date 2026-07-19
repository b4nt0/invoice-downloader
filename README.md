# Automated Invoice Downloader

Automated invoice downloader (hereinafter -- AID), is my hobby project that downloads invoices from websites that do not support a useful invoice API.

The project is a modular Python script that uses Playwright to automate the websites of well-known services to download the invoice PDFs for the last quarter.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Usage

```bash
aid init                 # write config.yml from the example
aid run                  # authenticate and download (default: config.yml)
aid run -c config.yml -v
```

Session cookies are stored under `.aid/sessions/`. Invoice PDFs go to the `output_directory` paths from the config.

## Specs

Please find [the specs](./docs/specs/) in the `docs/specs` directory.

## License

Please find [the license](./LICENSE) in the `LICENSE` file.
