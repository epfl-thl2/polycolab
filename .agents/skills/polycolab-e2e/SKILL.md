---
name: polycolab-e2e
description: Write, run, or debug Polycolab end-to-end browser tests. Use for Playwright journeys and real-service browser acceptance.
---

# Test Polycolab browser journeys

Run commands from the repository root.
Use this skill to choose a harness, exercise a user journey, and report what the result establishes.
Read [AGENTS.md](../../../AGENTS.md) for repository guidance.

## Choose the evidence needed

Identify the user action, expected observable result, and whether the change requires real API, storage, or worker behavior.
Inspect the nearest spec and its configuration before choosing a runner.

| Need                                                                | Harness                                                        |
| ------------------------------------------------------------------- | -------------------------------------------------------------- |
| Browser interactions with controlled API responses                  | Mocked specs in `tests/web/browser/specs/`                     |
| Browser behavior against compiled assets                            | Production-preview suite, still using mocked APIs              |
| Account, research, and upload flows in local mode                   | Disposable SQLite/filesystem smoke runner                      |
| Public research and external-agent authority with production assets | PostgreSQL/Garage research browser gate                        |
| Hosted-worker journeys and process recovery                         | PostgreSQL hosted-worker harness with a deterministic provider |

Read [runner instructions](references/runners.md) for the selected mode only.
Use the [system test guide](../../../tests/system/README.md) for real-service setup and specialized acceptance gates.
Mocked responses cannot establish authorization, persistence, worker execution, or deployment acceptance.

## Write or update a journey

- Put mocked browser specs in `tests/web/browser/specs/` and import `test` and `expect` from `../fixtures`. That fixture mocks `/api/v1/config`; configure capabilities deliberately when a scenario needs different behavior.
- Real-service specs live in `tests/system/specs/` or `tests/web/browser/local/`. Use their existing real-service setup and import Playwright directly; do not bring the mocked fixture into those suites.
- Exercise production routes through user actions and assert visible outcomes with role/label locators and Playwright's waiting assertions. Scope locators when the same label appears in several regions.
- Use independent browser contexts for distinct users or anonymous readers. Check denied operations and private-data visibility when the changed journey crosses an authority boundary.
- For mocked journeys, return contract-shaped data and handle the relevant request methods, paths, and failure responses explicitly. Assert an outgoing request when its payload is part of the behavior under test.
- Real APIs may create prerequisite data, but perform the action under test through the browser when the claim concerns a browser workflow. Verify persistence through a reload or fresh read when it matters.
- Avoid fixed sleeps, internal component state assertions, and broad mocks that make unrelated requests succeed. Keep fixtures deterministic and isolate data between tests.
- The production-preview configuration has an explicit `testMatch` list. Add a new spec there only when that journey needs compiled-asset coverage.

## Run and diagnose

Start with the changed spec or named journey; broaden coverage when the change affects shared navigation, authentication, configuration, or components.
Inspect the first failing assertion, browser errors, network responses, and runner startup output before changing a test or application code.
Separate a missing prerequisite or occupied port from a behavioral regression.
Use retained traces for synthetic fixtures when available; never enable persistent traces or publish DOM snapshots for the research gate that reveals a one-time credential.

Use disposable harness state for real-service tests.
The hosted-worker harness uses fixed service ports and a fixed Compose project; do not run it concurrently or stop unrelated services to free its ports.
Let each runner clean up its own services and data.

## Report the result

State the command, selected journey, outcome, and relevant evidence limits.
Name skipped or blocked tests and the missing prerequisite; a suite with skipped journeys does not verify them.
Include reproducible manual steps for changed user-facing behavior.
Keep failure artifacts outside commits and remove secrets from shared evidence.
