# Polycolab requirements

Polycolab helps mathematics and theoretical computer-science researchers develop ideas alone, with collaborators, and with AI agents.
A public research commons connects to public and private projects.
Statements organize notes, attempts, proofs, formalizations, and computational evidence.

These documents describe intended core features and interactions.
The [architecture](../architecture/README.md) describes the current implementation.
The [roadmap](../roadmap.md) identifies unfinished work.

## Core journey

1. Find a public statement or begin research in a project.
2. Inspect its assumptions, sources, and supporting work.
3. Develop ideas through conversation, direct editing, or an external agent.
4. Save statements, notes, attempts, and related research.
5. Check Lean formalizations or run Python computations.
6. Collaborate and choose which private results to publish.
7. Return to earlier work and continue the investigation.

## Guides

| Document                                         | Purpose                                            |
| ------------------------------------------------ | -------------------------------------------------- |
| [Functional requirements](functional.md)         | Core capabilities and user actions.                |
| [Human interface](human-interface.md)            | User journeys and interaction principles.          |
| [Shared Library](library.md)                     | Public statements, admission, and project copies.  |
| [Agent interface](agent-interface.md)            | Agent contributions and permission boundaries.     |
| [Non-functional requirements](non-functional.md) | Essential integrity, privacy, and usability rules. |

## Product boundaries

Public reading does not require an account.
Writing requires an authorized human or agent.
New projects default to public, with an explicit private option.
Owners control membership and visibility.

Agents can save contributions within their permissions without approval for each output.
Public Library admission and publication of private research remain human actions.
Private agent conversations do not automatically become shared research.

Authorship, human endorsement, formal checking, and computational evidence describe different properties.
Saving or admitting research does not establish mathematical correctness.

External MCP, Git/filesystem synchronization, advanced literature retrieval, persistent notebooks, GPUs, live coediting, and configurable agent builders remain future options.
