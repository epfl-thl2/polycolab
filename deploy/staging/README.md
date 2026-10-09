# Staging gate helpers

`staging-gate.md` is the evidence contract.
The GitHub workflow runs deterministic repository checks.
It blocks a release until the protected staging environment has an evidence reference for every external gate.
Never put provider keys, OIDC tokens, research content, or raw private events in workflow logs or artifacts.

Use a protected GitHub Environment named `staging` with required reviewers.
Set `STAGING_BASE_URL` as an environment secret/variable.
Use a short-lived operator credential only for the authenticated read probe.
The workflow prints only a normalized verification status, never project bodies or credentials.

Set `STAGING_BASE_URL` to the exact HTTPS application origin (no path, query, fragment or embedded credentials).
`STAGING_AUTH_MODE` defaults to `local`, the built-in provider.
Supply `STAGING_OPERATOR_SESSION` as a protected environment secret containing a valid built-in session token.
The cookie defaults to `polycolab_session`, configurable with `STAGING_AUTH_COOKIE_NAME`.

For OIDC, explicitly set `STAGING_AUTH_MODE=oidc`.
Supply a short-lived API access token through `STAGING_OPERATOR_TOKEN`.
The probe sends only the selected credential.
Never use an ID token, an anonymous request, or a production user's session for this gate.

The probe performs only GETs: it requires anonymous `/api/v1/projects` to return 401 and the selected authenticated read to return 200.
It neither follows redirects nor reads response bodies, and ignores ambient HTTP proxies.
It does not create accounts, log in, refresh or revoke sessions.
Obtain a short-lived dedicated test credential through the selected provider's normal flow.
Retire it after the gate.

Missing/expired credentials fail.
There is no alternate-mode fallback.

Local invocation with credentials already supplied through the environment:

```sh
uv run --directory src/backend python -m polycolab.staging_auth_probe
```

This HTTP smoke check does not prove browser login, cookie/CSRF behavior, logout, OIDC PKCE/JWKS rotation or deployment security.
Supply those separate results in the restricted evidence record.
The workflow validates the reference's format, not its contents: protected-environment reviewers must inspect the actual record.
