# Staging gate contract

Run this gate against the exact image SHA intended for release.
The gate record must contain UTC timestamps, operator, release SHA, environment, and links to logs/evidence.
A missing or manually asserted check is **not** a pass.

| Gate                    | Required evidence                                                                                                                                                                                                             | Owner            |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| Migrations              | one-shot migration job output and resulting revision                                                                                                                                                                          | API/release      |
| Health                  | Process liveness through `/health/live` and database readiness through `/health/ready`                                                                                                                                        | on-call          |
| Web delivery            | FastAPI serves the pinned Vite bundle and direct SPA routes without a Node.js runtime/service.                                                                                                                                | web/platform     |
| Public research pages   | Shared Library, record, and project pages work anonymously with JavaScript. The API returns the same 404 for private/nonexistent resources.                                                                                   | API/security     |
| Selected authentication | Built-in: pre-start administrator bootstrap, durable login limits, HTTPS cookies, login/logout/expiry and CSRF. OIDC if selected: issuer/JWKS/audience/PKCE and rotation. Both: anonymous denial and authorized private reads | identity         |
| Selected key backend    | Matching-context decrypt, mismatch denial, least-privilege policy, historical version reads and safe key-service failure for the configured OpenBao/AWS backend                                                               | security         |
| Real provider stream    | bounded real model stream, normalized terminal event, redacted usage                                                                                                                                                          | runtime          |
| Private worker          | worker has no public route and can only use scoped run capability                                                                                                                                                             | runtime/security |
| SSE proxy               | `text/event-stream`, buffering disabled, `Last-Event-ID` reconnect with no gaps/duplicates                                                                                                                                    | web/platform     |
| Auth leakage            | cross-project/role and anonymous public-read negative tests                                                                                                                                                                   | API/security     |
| Quotas                  | per-run/project/user time, output, tool-call and request limits reject overage                                                                                                                                                | API/runtime      |
| Backup restore          | encrypted backup checksum and isolated restore drill with measured RPO/RTO                                                                                                                                                    | operations       |

The workflow in [`.github/workflows/staging-gate.yml`](../../.github/workflows/staging-gate.yml) runs repository and local checks and provides a protected-environment checklist.
The staging operator must supply deployment-specific probes for provider, KMS, proxy, and private networking.
They must attach results to the gate record.
This repo does not fabricate those results.

Built-in accounts are the default.
OIDC/Keycloak is an operator choice, not a universal prerequisite.
Local development encryption is not a production key backend.
Follow the [probe configuration](README.md), [optional Keycloak checklist](../keycloak/README.md), [OpenBao checks](../openbao/VERIFY.md) and [recovery contract](../RECOVERY.md).
Use the [incident and rollback procedures](../INCIDENTS.md) for non-execution fault drills.
Each needs separate deployment evidence and reviewer sign-off.

Keep optional execution disabled until the [native gates](../../docs/architecture/hosted-failures.md) pass and the operator explicitly enables it for the target environment.
Record unexercised execution rows as deferred.
Independent non-execution checks do not satisfy them.
The workflow checks that an evidence reference is present and shaped correctly.
It does not inspect its contents or automatically prove every external gate.
