<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# API fundamentals

## Choose the correct authentication

- Anonymous requests can read public resources.
- The browser uses a secure same-origin session cookie for built-in accounts.
- External agents send `Authorization: Bearer <key>`.
- OIDC deployments accept access tokens issued by their configured provider.

Authentication does not expand project authority.
Each operation still applies the current role and resource policy documented in the [API reference](/docs/api).

## Paginate collections

Core collections return `items` and `next_cursor`.
Pass a returned cursor as the next request's `cursor`.
Keep identity, scope, and filters unchanged.
Stop when `next_cursor` is null.
The default page size is 25 and the maximum is 100.

## Save current files

Default project file reads return a content digest. Send that digest as `expected_digest` when updating, renaming, or deleting the file. A stale write returns a conflict; reread and reconcile before retrying. File history depends on the project's selected mode.

## Handle errors

Inspect the structured error response and HTTP status before deciding whether to retry.
Do not retry authorization, validation, or conflict failures as transient failures.
External agent file requests consume the key's request and mutation budgets. See [Agent identities and file access](agent-runs.md).
