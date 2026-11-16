# Web application

The Svelte application uses typed adapters over generated OpenAPI types. FastAPI serves built assets in production; Vite serves development separately. Browser routes require JavaScript.

`/` shows a home dashboard with search, recently updated projects, published Library items, account shortcuts, and getting-started links. Signed-in users see their active projects; visitors see public projects. Typing in search opens grouped project and Library results plus an Ask AI action. Results link directly to individual items. Homepage section links open the full directories at `/projects` and `/library`. The project directory retains its member/public scopes, filters, sorting, and project creation. Public visitors can read project metadata; project files and conversations require membership.

The homepage search opens on focus with search tips, without tracking recent activity. Typed queries show compact project and Library results plus an Ask AI action, with keyboard navigation and a fixed shortcut footer.

Ask AI opens a project-independent research assistant dialog with the question prefilled. Signed-in users send the question to a shared platform-managed model without selecting a personal provider connection. This text-only chat stays in browser memory while the homepage is mounted; it is not part of saved conversation history. Closing the dialog preserves the chat, while New chat, navigation away, reload, or account changes clear it. The assistant has no project-file access or live web search. Missing platform model configuration and request failures are explicit UI states.

Projects choose Basic, Collaborative, or Git workbenches. They retain file explorers, editors, conversation tabs, settings, and Agent connect. Basic projects operate on current server files with guarded saves. Git and Collaborative retain their respective file history and collaboration interfaces. LaTeX builds are available where the saved-file capability supports them.

Chat drafts survive tab switches and are cleared with account/project teardown. Query caches are cleared on sign-out and authentication changes. Hosted conversations retain provider selection, streaming events, cancellation, and project artifact IDs as optional context.

The homepage's “Onboard your agent” button displays the Codex, Claude Code, OpenCode, and Pi logos and opens a setup modal with an API-key settings link and copyable instructions using the current site's `/SKILL.md`. The full connection guide remains available from the modal. External agent API keys currently support Basic project files, not conversations.

Account settings contain provider connections, API keys, identity, and recovery. `/library` remains the independent agent-content library, and API key settings live at `/settings/api-keys`. About, documentation, sign-in, and account recovery remain public routes.

Research-object editors, maps, activity feeds, contribution profiles, commons, catalogue, publications, proposal reviews, and verification pages are absent. Stored tabs for removed research routes are discarded. Old `/workspaces` bookmarks for surviving project routes still normalize to `/projects`.

Local notifications are transient UI feedback; they do not use a research event database. Public metadata never implies public file access.
