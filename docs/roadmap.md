# Roadmap

This page lists unfinished capabilities and acceptance work.
It is not a delivery schedule.
Product requirements define the intended behavior.
The [architecture index](architecture/README.md) describes existing foundations.

## Product work

| Area                       | Remaining work                                                                                                                                                                                                                                                                           |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Research editing           | Authorized object deletion and restoration with retained history, exact references, and independently published copies. Define the role/ownership policy before implementing it.                                                                                                         |
| Verification               | Production Lean and Python runners, exact declaration/policy observations, authorized cache reuse, and selective publication of verified evidence. Existing job, artifact, source-editor, and result-view foundations do not establish machine assurance.                                |
| Agent customization        | Saved custom-agent profiles, runtime activation of library content, bundled skills, project-only sharing, bookmarks and improvement proposals. The [agent library](architecture/agent-library.md) provides public discovery and human contribution.                                      |
| Hosted agents              | Complete the remaining [hosted acceptance gates](architecture/hosted-failures.md#native-gates-still-required), including resource exhaustion, daemon outage, reboot and live-provider acceptance for each enabled backend. Docker/gVisor and microsandbox share the hardened controller. |
| Community and accounts     | Connect general Chat. Complete profile editing, bios, interests, pins, account-session management, and membership-entry guidance. Public contribution profiles are available through direct username links; a people directory is not part of the product.                               |
| Browsing and accessibility | Preserve list filters and position across navigation. Validate keyboard/focus, mobile reading, accessible mathematics, and research inspection with representative users.                                                                                                                |
| Persistence boundaries     | Complete service-to-store conversion where application services still use SQL directly. See [persistence](architecture/persistence.md#implemented-and-remaining-conversion).                                                                                                             |
| Scheduling and capacity    | Complete verification scheduling. Measure fairness and capacity. The [hosted controller](architecture/hosted-controller.md) describes the existing agent allocator. Stored policy alone does not establish service guarantees.                                                           |

External MCP, Git/filesystem synchronization, literature retrieval, persistent notebooks, GPUs, live coediting, and configurable agent builders remain candidates on this branch.
They are not prerequisites for the existing browser and shared HTTPS API.

## Design decisions to resolve

- Decide which research kinds appear directly on the map and which appear through inspectors and lists.
  See [object presentation](architecture/object-kinds-and-reviews.md).

These questions do not change existing authorization or grant new write access.

## Release acceptance

Use the checks documented in the [agent guidance](../AGENTS.md#verify-changes).
Real PostgreSQL, API, storage, worker, and browser evidence follows the [system test guide](../tests/system/README.md).
Deployment-specific checks follow the [staging gate](../deploy/staging/staging-gate.md).

Before making production claims, verify:

- Populated schema upgrades and coordinated database, object-storage, and key recovery, with preserved research identities and immutable public releases.
- The selected authentication providers, HTTPS ingress, registration limits, credential rotation, and cross-scope denials on the target deployment.
- Native sandbox containment and recovery before enabling agent execution.
  Lean/Python verification requires its own runner and evidence acceptance.
- Browser responsiveness on a documented device and production build, including large research lists and relationship maps.
- Researchers finding and resuming work, distinguishing evidence from proof, and sharing intentionally.

Keep dated measurements and deployment evidence with the release record.
Update this page when the remaining work changes.
Do not append milestone journals.

## Linear project rollout

Linear mode is available through the project mode selector.
Native protocol-5 guest refresh/completion acceptance and target-deployment
backup/recovery and reconnect checks remain deployment verification work.
See the [implemented contract](architecture/linear-projects.md).
