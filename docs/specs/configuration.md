# AID configuration

AID is configured with the help of a YAML configuration file. See the full syntax example in the [sample config](../../config.example.yml).

Configuration keys:

## `services`

The `services` key contains configuration for individual services. Every service key is used to discover the relevant service module.

### `enabled`

Must be `true` for AID to use the service. Services that have their `enabled` set to `false` are ignored. The default value is `true`.

### `relative_date_range`

Invoice date interval relative to the current date. Currently only `last_quarter` value is supported.

- `last_quarter` - the latest finished calendar quarter of the year. For example, Q2 is 1st of April till 30th of June, both dates includes.

### `output_directory`

The directory relative to the script executable where the downloaded invoice files must be placed.

### `login_url`

The URL of the login page of the service.

### `dashboard_url`

The URL of the dashboard that is the starting point for the service script.

### `dashboard_marker`

A text that, if specified, must be present on the dashboard page for the probe to be successful.

## `login_markers`

A list of strings that is used by the [authentication flow](./download-flow.md) to detect a redirect to an authentication page.

## `download`

Download options.

### `format`

A format string that uses `strftime` format labels.
