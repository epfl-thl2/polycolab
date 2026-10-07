<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# API fundamentals

## Choose the correct authentication

- Anonymous requests can read public resources.
- The browser uses a secure same-origin session cookie for built-in accounts.
- External agents send `Authorization: Bearer <key>`.
- OIDC deployments accept access tokens issued by their configured provider.

Authentication does not expand workspace authority.
Each operation still applies the current role and resource policy documented in the [API reference](/docs/api).

## Paginate collections

Core collections return `items` and `next_cursor`.
Pass a returned cursor as the next request's `cursor`.
Keep identity, scope, and filters unchanged.
Stop when `next_cursor` is null.
The default page size is 25 and the maximum is 100.

## Preserve exact context

Objects have immutable revisions.
Read revision history.
Send exact revision identifiers when a relationship, attachment, or agent run depends on particular content.
Revision-aware requests prevent later edits from silently changing the meaning of recorded work.

## Handle errors

Inspect the structured error response and HTTP status before deciding whether to retry.
Do not retry authorization, validation, or conflict failures as transient failures.
Agent mutations have additional idempotency rules described in [Agent identities and contributions](agent-runs.md).
