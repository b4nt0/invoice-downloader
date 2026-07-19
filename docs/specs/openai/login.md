# OpenAI login and CAPTCHA

OpenAI's login (Auth0 + Google reCAPTCHA) often rejects AID's interactive browser even when you tick the checkbox yourself. The page may loop: checkbox → spinner → checkbox again.

## Why Playwright sessions fail

1. **CAPTCHA** — Google treats any Playwright-controlled browser as automated, including `playwright codegen --channel=chrome`.
2. **Cookie export is not enough** — exporting `storage_state` JSON from a logged-in Chrome profile typically captures cookies but **not** Auth0 localStorage / IndexedDB. AID then opens Playwright Chromium with incomplete auth and gets redirected to login (and CAPTCHA) again.

The working approach is to keep the session in a **dedicated Chrome profile on disk** and let AID open that profile directly (`user_data_dir` + `browser_channel: chrome` in config). Do not rely on `.aid/sessions/openai.json` for OpenAI.

## One-time setup

### 1. Config

In `config.yml` (already in `config.example.yml`):

```yaml
openai:
  ...
  user_data_dir: ".aid/chrome-openai"
  browser_channel: "chrome"
```

### 2. Sign in with plain Chrome (no Playwright)

Quit any Chrome window that already uses this profile, then from the project root:

```bash
mkdir -p .aid/chrome-openai

open -na "Google Chrome" --args \
  --user-data-dir="$PWD/.aid/chrome-openai" \
  "https://platform.openai.com/login"
```

1. Complete login and CAPTCHA.
2. Open [Billing history](https://platform.openai.com/settings/organization/billing/history) and confirm invoices load.
3. Quit Chrome completely (Cmd+Q) so the profile is not locked.

`.aid/` is gitignored.

### 3. Run AID

```bash
aid debug   # or aid run
```

AID launches Chrome with `.aid/chrome-openai`. If the profile is still signed in, the auth probe succeeds and download continues. If not, AID opens the same profile for interactive login (CAPTCHA may still block Playwright-attached Chrome — prefer step 2).

You can delete a leftover `.aid/sessions/openai.json`; OpenAI auth ignores it when `user_data_dir` is set.

## When the session expires

Sign in again with the plain-Chrome command in step 2 (same `user_data_dir`). Then rerun AID.

If Chrome says the profile is in use, quit every Chrome window using that profile (Cmd+Q), wait a second, and retry.
