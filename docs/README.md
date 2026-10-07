# Polycolab documentation

Start with the guide for your task:

| Task                                          | Guide                                                               |
| --------------------------------------------- | ------------------------------------------------------------------- |
| Run Polycolab locally                         | [Project README](../README.md#run-locally-or-with-docker)           |
| Use workspaces, research, and agents          | [User guides](../docs-site/docs/index.md)                           |
| Understand the product and its requirements   | [Requirements](requirements/README.md)                              |
| Understand the implementation                 | [Architecture](architecture/README.md)                              |
| Find source code and tests                    | [Repository map](../README.md#repository-map)                       |
| Work on the repository with a coding agent    | [Repository skill](../.agents/skills/polycolab-repository/SKILL.md) |
| Integrate an external agent                   | [Shared research API](architecture/external-agent-api.md)           |
| Deploy, operate, or recover the service       | [Deployment](../deploy/README.md)                                   |
| Run integration checks                        | [System tests](../tests/system/README.md)                           |
| See unfinished capabilities and release gates | [Roadmap](roadmap.md)                                               |

The generated [OpenAPI snapshot](../packages/api-client/openapi.json) lives with the TypeScript client.
Run `pnpm run api:contract` after API changes.
Do not edit generated files by hand.

See [Workspace files](architecture/workspace-files.md) for Git-backed task working copies, collaboration, and coordinated backups.

## Authority

After an explicit task or design decision, use this order when documents disagree:

1. Product requirements define intended behavior.
2. Architecture documents describe the current implementation.
   Source code resolves discrepancies about what exists.
3. Explanatory guides provide context.

An implementation claim, an automated check, deployment acceptance, and user validation are separate facts.
Planned services and demo fixtures must be labelled as such.
Historical test counts do not establish the state of a later revision.

## Maintenance

Keep `docs/` for documentation only.
Keep each contract in one place.
Link to that contract from other documents.
Update the affected document when behavior changes.
Remove superseded instructions.

Keep `architecture/` flat and limited to implemented behavior.
Keep product gaps in the roadmap and proposed designs in issues.

Agent progress logs, handoffs, worktree inventories, session transcripts, and dated acceptance journals do not belong in this documentation.
Use issues and pull requests for delivery discussion, CI for test results, and private operations records for deployment evidence.
The private repository history preserves earlier development records.
The public documentation describes the maintained product.
