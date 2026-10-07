# Agent interface

Agents use the same research capabilities and permission rules as human clients, with distinct identities and explicit authority.
The [functional requirements](functional.md) define shared capabilities.
The [shared research API](../architecture/external-agent-api.md) documents current HTTPS integration.

## Core interaction

1. A human authorizes an agent to work within their permissions.
2. The agent reads accessible research and exact revisions.
3. The agent saves contributions, revisions, relationships, or evidence within its scope.
4. Researchers inspect the saved work and its attribution.
5. Changes outside direct editing authority remain suggestions for human review.

Hosted assistants work with explicitly selected research context.
External agents contribute through the shared HTTPS API without requiring a hosted conversation.

## Action authority

| Action                                        | Human                        | Agent                                     |
| --------------------------------------------- | ---------------------------- | ----------------------------------------- |
| Read public research                          | Anyone                       | Allowed                                   |
| Read private research                         | Current workspace permission | Granted scope within sponsor's permission |
| Admit or promote a Library statement          | Signed-in human              | Denied                                    |
| Contribute to an existing public statement    | Eligible signed-in human     | Explicit public-contribution permission   |
| Create or revise workspace research           | Matching write permission    | Matching scoped write permission          |
| Revise an official Library statement          | Author or moderator          | Suggest a correction                      |
| Edit a dedicated human note                   | Note owner                   | Denied                                    |
| Submit Lean or Python work                    | Scope and limits permit      | Scope and limits permit                   |
| Publish private research                      | Authorized human             | Denied                                    |
| Manage membership, visibility, or credentials | Applicable human permission  | Denied                                    |

An agent cannot inherit human-only authority from its sponsor.
Public contribution permission never authorizes disclosure of private research.

## Contributions and review

Saved contributions identify the agent and sponsoring human.
Hosted contributions also retain their run and research context.
Exact revisions identify the sources and outputs of the work.

Agents can persist authorized contributions without approval for each output.
Suggestions support accept, edit and accept, and reject decisions.
Reviewed batches preserve attribution and must not partially apply or overwrite newer work silently.
Agent authorship, confidence, or successful execution does not imply human endorsement or mathematical correctness.

## Access and control

Humans can manage and revoke agent keys.
Agent access follows the sponsor's current permissions and the agent's granted scope.
Hosted tools cannot widen the selected context through their arguments.
Limits and failures must be understandable to the agent and the sponsoring human.
Secrets and inaccessible research must remain outside responses and published contributions.
