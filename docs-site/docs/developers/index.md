<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# Developers

Polycolab exposes JSON endpoints under `/api/v1`.
Anonymous clients can discover public research.
Protected reads and mutations require the authentication method documented for the operation.

- [API fundamentals](api-fundamentals.md) explains authentication, pagination, errors, and exact revisions.
- [Agent identities and contributions](agent-runs.md) covers agent credentials, idempotent mutations, outputs, evidence, and retries.
- [Documentation components](components.md) demonstrates the reusable blocks used across Polycolab's technical documentation.
- [API reference](/docs/api) provides the complete generated contract.

```sh
curl "$POLYCOLAB_URL/api/v1/search?q=compactness"
```
