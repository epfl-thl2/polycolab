# Polycolab architecture

Polycolab is a modular FastAPI application with a Svelte browser client, PostgreSQL persistence, immutable research versions, and private agent execution interfaces.
FastAPI owns authorization and canonical application state.
The browser uses the generated TypeScript client.
Workers use authenticated APIs and receive no database credential.

## Runtime boundaries

- The Svelte browser uses the generated TypeScript client.
  FastAPI serves the production browser bundle and public/private APIs.
- FastAPI owns authorization, research changes, and canonical PostgreSQL state.
  Local development uses SQLite with separate migrations.
- Artifact metadata lives in the database.
  Bytes use configured object storage or the local development filesystem.
- Private workers call authenticated APIs.
  They receive scoped capabilities, never database or provider credentials.
- The Model Gateway protects provider keys and bounds inference requests.

## Technical contracts

These documents describe code present in this repository.
Each document identifies optional runtime capabilities and deployment boundaries that still require verification:

| Contract                                                  | Scope                                                                            |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Application configuration](application-configuration.md) | Project visibility, optional runtime capabilities, and deployment settings       |
| [Object kinds and reviews](object-kinds-and-reviews.md)   | Current vocabulary, exact-version review signals, and relationship presentation  |
| [Research versions](research-versions.md)                 | Immutable snapshots, exact relationships, history, and concurrency guards        |
| [Research schema](research-schema.md)                     | Stored state, integrity boundaries, and supported migration paths                |
| [Persistence](persistence.md)                             | Application entities, stores, SQL adapters, and shared transactions              |
| [Shared research API](external-agent-api.md)              | Account-wide agent keys, scoped direct contributions, evidence, and public reads |
| [HTTP API](api.md)                                        | Browser, research, private runtime, and hosted-tool contracts                    |
| [Catalogue](catalogue.md)                                 | Human admission, official versions, moderation, and publication                  |
| [Web application](web.md)                                 | Svelte delivery, authentication, navigation, and browser state                   |
| [Agent runtime](agent-runtime.md)                         | Private worker lifecycle and durable events                                      |
| [Hosted controller](hosted-controller.md)                 | Implemented controller candidate and outstanding native acceptance               |
| [Hosted failure handling](hosted-failures.md)             | Recovery behavior, known defects, and required deployment checks                 |
| [Model gateway](model-gateway.md)                         | Provider access, protected credentials, and network policy                       |

See [Project files](project-files.md) for API-owned Git storage, shared task working copies, hosted checkout, and Git/SQL recovery.

Scoped direct contributions and optional human-reviewed proposals both exist.
Human-only catalogue admission and publication remain separate policy boundaries.
Job and artifact foundations do not imply that production Lean/Python runners or machine assurance are available.

Each contract states its implementation limitations.
Unfinished capabilities belong in the [roadmap](../roadmap.md).
Operational setup belongs in the [deployment guide](../../deploy/README.md).
