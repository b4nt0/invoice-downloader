# AID invoice download flow

The [orchestrator](./architecture.md) flow launches independent browser automation sessions per service.

Every session goes through the authentication and download phases. The following phases are per service.

## Authentication phase

Interactive authentication is optional. It only kicks in if AID is not authenticated already.

If there's a saved session, the orchestrator script immediately launches a headless browser that probes for authentication.

### Authentication probe

The orchestrator service restores the previously saved authenticated session. Then it tries to navigate to the `dashboard_url` of the service.

#### Failure detection

Authentication probe is considered failed if one of the following conditions are met:

1. The browser is redirected to a URL that matches the `login_url` (save the URL query string).

2. The browser is redirected to a URL that does not match the `login_url`, but where the page title contains at least one string from the `login_markers`.

In all other cases, the authentication probe is considered successful.

#### When the authentication probe fails

The orchestrator script stops the authentication probe session and falls back to the interactive authentication session.

#### When the authentication probe succeeeds
The orchestrator script stays in the headless session and passes control to the service script.

### Interactive authentication

The orchestrator script launches an interactive browser, navigates it to the `login_url` of the service, collects the user authentication, and returns back to the authentication probe.

### Infinite cycle prevention

When the user cannot authenticate, the algorithm above can result in an infinite loop. To prevent it, AID tries interactive authentication not more than once per launch.

## Download phase

As soon as the authentication probe passes, the orchestrator script makes sure that the download directory exists and passes control over the headless session to the service script.

The orchestrator script converts the relative date interval to an absolute date interval with the precision of a day.

It is the job of the service module to convert this to specific invoices. For example, Heroku uses monthly invoices.

It is the job of the service module to save the invoice files and handle possible file name collisions by adding sequential integer suffixes.

The orchestrator sets a timeout of `10` minutes for every download phase.

## Services sequencing

The orchestrator sequences services in such a way that the user receives interactive authentication prompts for different services as soon as possible after the script start, but never in parallel, and always in order that they are specified in the configuration.

This means that the orchestrator first makes sure that one service is authenticated before launching authentication for the next service. Orchestrator waits for the previous service successful authentication, but does not wait for the successful file download. Invoice downloads run in parallel.
