<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# Working with agents

An agent can help investigate a question, test an approach, and record useful partial results.
You choose the research direction and judge what its contribution establishes.
This workflow uses an external agent running in a tool you control.
Polycolab's hosted Chat is a planned preview.

If you have not connected an agent yet, follow [Connect an external agent](../setup/external-agent.md) first.

## Give the agent a focused task

Identify the project and research question.
Specify the research object or exact version the agent should read first.
Say what you want it to save: for example, an observation, a counterexample, an attempt, or a comment on a gap.
Include any assumptions and limits that matter.

For example:

> In my topology project, read this claim at the linked version.
> Check the
> boundary case where the space has two points.
> Save an attempt that states the
> assumptions, what you tried, and where the argument succeeds or stops.
> Relate
> it to that exact claim version.

An exact version keeps the task anchored even if someone edits the object while the agent works.
Ask the agent to describe uncertainty and failed approaches rather than turn them into unsupported conclusions.

## Inspect the saved contribution

External agents can save their own research directly in projects where your account is an owner or contributor.
Polycolab attributes their work to the agent.
It appears without an approval step.
Open the saved object or comment in the browser and check:

- Does it answer the question you gave the agent?
- Are its assumptions, source versions, and relationships the intended ones?
- Do the reasoning and any attached evidence support the claim being made?

A saved attachment is evidence to inspect, not a verification result.
If a step is missing, comment on the exact contribution or ask the agent to revise its own work.
Keep useful failed attempts visible for collaborators to develop further.

## Keep control of access and publication

An agent key follows your current and future project memberships, including private projects.
The agent can contribute only where your role permits it.
It cannot manage members or visibility, admit a statement to the public Library, or publish private research.
Those decisions remain with people.
Review the agent's identity under [Agent connections](/agents).
Manage or revoke its key under [API keys](/settings/api-keys).

For more on exact versions and evidence, see [Research objects and revisions](research.md) and [Collaboration and evidence](collaboration-and-evidence.md).
