# Polycolab architecture

Polycolab combines a Svelte browser, FastAPI, project files, database metadata, and optional private execution workers. A project is the shared human and agent workspace.

FastAPI owns authorization and production PostgreSQL state. SQLite has a separate local migration chain. Files use Default server directories, Git worktrees, or Linear storage. Artifact metadata references projects directly; object storage holds bytes. Private workers call authenticated APIs without database credentials.

## Technical contracts

| Contract                                      | Scope                                            |
| --------------------------------------------- | ------------------------------------------------ |
| [Configuration](application-configuration.md) | Core behavior and optional execution/recovery    |
| [Persistence](persistence.md)                 | Entities, stores, transactions, and migrations   |
| [Default projects](default-projects.md)       | Current files and external-key access            |
| [Linear projects](linear-projects.md)         | Live collaboration and snapshots                 |
| [Git project files](project-files.md)         | Worktrees, commits, and recovery                 |
| [External agent API](external-agent-api.md)   | Keys, membership, budgets, and file commands     |
| [HTTP API](api.md)                            | Public contract and private worker boundary      |
| [Web application](web.md)                     | Routes, navigation, authentication, and drafts   |
| [Agent runtime](agent-runtime.md)             | Sessions, capabilities, execution, and artifacts |
| [Hosted controller](hosted-controller.md)     | Execution isolation and deployment gates         |
| [Hosted failures](hosted-failures.md)         | Recovery behavior                                |
| [Model gateway](model-gateway.md)             | Provider keys and inference requests             |
| [Agent library](agent-library.md)             | Reusable instructions and plugin listings        |
| [Direct chat](chat.md)                        | Provider chat without a worker                   |

Research-object storage, catalogue, commons, publication, and verification services have been removed. Historical migrations remain so existing installations can upgrade.
