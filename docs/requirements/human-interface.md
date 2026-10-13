# Human interface

The interface helps researchers find a problem, understand existing work, develop an idea, and resume an investigation.
Support researchers with different levels of programming experience.
Conversation and direct editing are two ways to work in the same project.

## Find and begin work

Let anyone browse public projects and Library entries.
Provide search and filters for relevant statements and supporting work.
Show assumptions, sources, status, and authorship before asking a reader to contribute.

After sign-in, let researchers create a project or copy a Library entry into an existing project.
Explain visibility before creation.
Make the private option easy to choose.
Preserve the intended destination through sign-in.

## Develop research

Keep the current project and task clear.
Provide research lists and a relationship map, with readable titles and meaningful links.
Keep objects accessible through lists as well as the map.

While reading an object, make its content and related work easy to inspect:

- Notes, summaries, comments, and progress.
- Alternative proof sketches and their premises.
- Successful and failed attempts.
- Formalizations, computations, and evidence.
- History, authorship, and exact source revisions.

Make creation, editing, saving, deletion, and restoration easy to find.
Show whether the user is editing a draft or reading saved work.
Explain conflicts without discarding the user's changes.
Before deletion, identify the object and explain its effect on history, references, and published copies.
Require confirmation.

## Project panes and tabs

The project uses four panes. A thin navigation rail at the far left provides
icons for existing project pages at a fixed width, with accessible labels and
tooltips. Hover and keyboard focus do not expand it. Rail selections switch page
layouts. In the Project layout, the left panel lists Main and named worktrees,
with the current user's conversations nested beneath each. The middle panel holds unified tabs
for chats, files, research objects, and diffs, with New chat as the default view.
The right panel switches between Explorer, Source control, and Details.

- **Keep navigation distinct from content.** Page navigation belongs in the
  far-left rail; worktrees and their conversations belong in the left panel. Make
  the selected worktree, conversation, and content tab clear. Selecting a worktree
  switches Explorer to its files. New conversations use the selected worktree.
- **Keep context stable.** Switching tabs or right-panel tools preserves drafts,
  selections, and positions. New AI output should not replace what the user is
  inspecting or editing without their action.
- **Keep edits understandable.** Show which tabs contain unsaved changes and
  whether content is being previewed, edited, or saved. Associate creation,
  editing, and deletion controls with the object or file they affect. Closing a
  tab must preserve unsaved work or ask before discarding it.
- **Use space deliberately.** Allow panels to be resized or collapsed, preserving
  the user's layout preferences. Explorer opens files in middle-panel tabs;
  Source control exposes changes and diffs; Details shows relevant context and
  actions for the active content.
- **Adapt to small screens.** Provide focused views and clear return actions while
  preserving the same task, active tab, and editing state. Keep navigation,
  conversations, and right-panel tools reachable.

## Main panel and right panel

The main panel holds the current task.
The right panel provides supporting content tied to that task.

| Main task            | Supporting interaction                                                 |
| -------------------- | ---------------------------------------------------------------------- |
| Conversation         | Inspect or edit a saved output while keeping the conversation visible. |
| Research list or map | Preview an object and access its actions.                              |
| Reading or editing   | Inspect related research, evidence, history, or AI assistance.         |

Keep the selected object and the relationship between panels clear.
Let users open a preview for detailed work and return to the previous view.
Opening or closing a panel preserves drafts, selection, and browsing position.
New AI output must not replace content the user is inspecting without their action.
On small screens, show supporting content as a focused view with a clear return action.

## Work with an assistant

Keep the conversation and composer prominent.
Make the assistant's role and selected research context understandable.
Connect saved outputs to the objects they create or use.
Distinguish suggestions, drafts, and saved contributions.

Show whether the assistant is working, waiting, finished, or unable to continue.
Provide cancellation and appropriate recovery actions.
Retain unsent text after failures.
Keep private conversation separate from research selected for sharing.

## Check results

For Lean, show source, declarations, assumptions, diagnostics, and check history.
Distinguish incomplete checks, complete proofs, and correspondence to the informal statement.

For Python, show code, inputs, outputs, and the scope of the computation.
Keep a certificate's separate checker result distinguishable from execution success.

Both flows show execution state, limits, cancellation, and rerun actions.
Make clear which exact research revision a result checks.

## Collaborate and share

Make owner, contributor, and read-only permissions understandable.
Keep project membership separate from personal account settings.
Show who contributed research and whether an actor is human or an agent.

Let researchers inspect and endorse saved work.
Where suggestions require review, provide accept, edit and accept, and reject actions.
Explain stale suggestions before applying them.

Before changing project visibility, explain the audience.
Require confirmation.
For selective publication, preview the chosen records and required dependencies.
Explain any private dependency that prevents publication.

## Resume work

Make previous conversations, saved research, followed statements, and recent changes easy to find.
Preserve search, filters, and browsing position when users return.
Activity and public profiles link to underlying research and respect visibility.
Keep private activity out of public counts.

## Interaction principles

Use clear labels, semantic controls, keyboard navigation, and readable mathematics.
Introduce advanced tools in the context of the user's task.
Distinguish visibility, endorsement, verification, stale revisions, and failures without relying only on color.
Preserve drafts and useful content after errors.
Show a safe next action and distinguish loading, empty, and unavailable states.
Label examples and unfinished capabilities clearly.
