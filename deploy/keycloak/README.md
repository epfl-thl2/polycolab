# Optional Keycloak realm reference

Built-in accounts remain the default in every environment.
This reference is only for organizations that explicitly select `AUTH_MODE=oidc`.
It provisions no user, password, client secret, container or server automatically.

`polycolab-realm.json` is an import template, not a deployed or live-accepted realm.
Make an operator-controlled copy outside the repository.
Replace every `https://polycolab.example.org` with the application's exact HTTPS origin.
Keep both browser callback paths: `/oidc/callback` and `/oidc/silent-callback`.
Keep the exact post-logout `/` URL.
Do not introduce wildcard redirect URIs/origins.

The public browser client uses authorization code flow with mandatory S256 PKCE.
Implicit flow, password grants, service accounts and full-scope access are disabled.
The audience mapper adds `polycolab-api` only to access tokens.
The browser uses `polycolab-web`.
No confidential client secret belongs in its configuration.

User enrollment is an operator choice.
Self-registration is disabled in the template.
Configure SMTP/reset-password delivery and the organization's MFA, password/session and account-recovery policies before inviting users.

For an issuer hosted at `https://identity.example.org`, configure the API with:

```dotenv
AUTH_MODE=oidc
OIDC_ISSUER=https://identity.example.org/realms/polycolab
OIDC_JWKS_URL=https://identity.example.org/realms/polycolab/protocol/openid-connect/certs
OIDC_CLIENT_ID=polycolab-web
OIDC_AUDIENCE=polycolab-api
OIDC_AUTHORIZED_PARTY=polycolab-web
```

The issuer must be the same externally reachable HTTPS identity for browser and API validation.
Do not substitute an internal container hostname in issuer claims.
Switching modes does not link or migrate built-in account identities to OIDC subjects.
Agree an account migration plan first.

## Provisioning and acceptance

1. Select an operator-supported Keycloak release.
   Pin its image digest.
   Provision its separate persistent database, TLS/hostname configuration, restricted admin access, bootstrap credential handling and backups.
   Do not use `start-dev` as a production deployment or reuse Polycolab's database credentials.
2. Review the modified realm.
   Import it through Keycloak's supported import flow.
   Startup `--import-realm` loads JSON from `/opt/keycloak/data/import` and skips an existing realm.
   Changing the file does not reconcile an existing realm.
   Never force an overwrite of a populated realm as a routine application upgrade.
3. Verify discovery, authorization code + S256 PKCE, both callback routes, access token issuer/audience/authorized-party, expiry, logout and account switching.
   Verify wrong-issuer/audience and ID tokens are rejected as API credentials.
4. Rotate signing keys.
   Exercise JWKS refresh with overlap for valid old tokens.
   Test unavailable discovery/JWKS.
   Test revoked users/sessions according to actual token/session lifetimes.
   Do not claim immediate JWT revocation without evidence.
5. Record release digest, settings, browser/API results, and recovery evidence.
   Complete these checks before claiming reference deployment acceptance.
   Existing mocked OIDC tests and static template tests do not prove these live flows.

Official references checked for this template: [container configuration](https://www.keycloak.org/server/containers), [realm import behavior](https://www.keycloak.org/server/importExport), [OIDC endpoints](https://www.keycloak.org/securing-apps/oidc-layers), and [audience protocol mapper](https://www.keycloak.org/admin-api/protocol-mappers).
