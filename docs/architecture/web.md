# Web application

The Svelte application uses typed adapters over generated OpenAPI types. FastAPI serves built assets in production; Vite serves development separately. Browser routes require JavaScript.

`/` and `/projects` show the project directory. Member and public scopes use the same project API. Public visitors can read project metadata; project files and conversations require membership.

Projects choose Default, Linear, or Git workbenches. They retain file explorers, editors, conversation tabs, settings, and Agent connect. Default projects operate on current server files with guarded saves. Git and Linear retain their respective file history and collaboration interfaces. LaTeX builds are available where the saved-file capability supports them.

Chat drafts survive tab switches and are cleared with account/project teardown. Query caches are cleared on sign-out and authentication changes. Hosted sessions retain provider selection, streaming events, cancellation, and project artifact IDs as optional context.

Account settings contain model providers, API keys, identity, and recovery. `/agents` remains the independent agent-content library, and `/agents/connections` manages named external agents. About, documentation, sign-in, and account recovery remain public routes.

Research-object editors, maps, activity feeds, contribution profiles, commons, catalogue, publications, proposal reviews, and verification pages are absent. Stored tabs for removed research routes are discarded. Old `/workspaces` bookmarks for surviving project routes still normalize to `/projects`.

Local notifications are transient UI feedback; they do not use a research event database. Public metadata never implies public file access.
