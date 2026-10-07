# Unified application configuration

Polycolab has one product configuration.
Public and private workspaces share the same routes and research model.
Creation and new-workspace Library imports default to public.
Users can explicitly select private.
Owners can change visibility.
Existing workspaces are not converted automatically.

Making a workspace private does not retract downloaded copies or separately published Library releases.

Public workspaces, Library, external-agent access, artifacts, and scoped direct contributions are standard features, with no deployment feature switches.
Workspace visibility, membership, credential scope, and human-only admission and publication rules still govern access.
Version-1 sessions retain their tool contract.
Public workspace saves never automatically become Library entries.

`GET /api/v1/config` returns typed public booleans: `agent_execution`, `verification_submission`, `verification_execution`, and `email_recovery`.
The browser loads these through the generated client.
A failed configuration read leaves execution/recovery actions unavailable with a retry control, but never blocks workspace creation, Library, agent keys, or artifact controls.
Configuration contains no operator identities, credentials, internal URLs, or actor-specific permissions.
Every server operation still enforces current authorization and execution gates.

Configure all five artifact storage connection fields together.
A host-run local API may start without storage, but byte operations then return `503 artifact_storage_unavailable`.
Metadata retains its normal access policy.
Production preflight requires storage configuration and its live check always includes bucket readiness.
Compose starts Garage and the community consumer by default.
Only the hosted worker retains an optional execution profile.

Settings ignore the five removed `FEATURE_*` environment variables.
Operators should delete them from deployment secrets.
This change does not migrate workspace visibility, research data, or credential scope.

The same web image works across configurations: there is no artifact build flag or separate execution UI constant.
Users can inspect existing session and verification history while new execution is disabled.
New hosted execution defaults off.
Configured social providers come from `/auth/config`.
Recovery UI requires local authentication, SMTP settings and a public origin.
Mail queue delivery remains an operator integration requirement.

This repository has no SMTP delivery daemon.
Do not configure recovery as available until that delivery path is operational.
Unfinished Chat, directory and session-administration services remain planned.

`PUBLIC_WORKSPACE_MODERATOR_SUBJECTS` is the explicit human allowlist for hiding or restoring public-workspace research.
It is separate from catalogue operators.
Workspace ownership does not grant deployment-wide moderation authority.

## Deployment and migration

Use the [deployment guide](../../deploy/README.md).
A fresh deployment uses the existing migration chain through `20260916_merge_versions_main`, joining canonical version relationships and hosted execution/submission history.
The earlier unification migration removes tutorial installation bookkeeping only.
It does not delete workspaces, research, accounts, immutable history or general recovery tables.
Historical migration names remain stable.

Persistent SQLite development databases have a separate forward migration through `local_20260916_versions`.
It backfills canonical directed and symmetric relationships, preserves declaration IDs, replaces legacy structural tables, and retains historical version content.
The local upgrader creates backups of existing databases and reverses failed upgrades.
It does not stamp unversioned databases.
PostgreSQL remains the deployment authority with database-enforced immutable relationship constraints.

Acceptance requires visibility transition tests, runtime capability/UI agreement, contract freshness, an empty-database migration check, and the general research and coordinated recovery harnesses.
Local tests do not establish deployment readiness, mail delivery or Linux execution isolation.
