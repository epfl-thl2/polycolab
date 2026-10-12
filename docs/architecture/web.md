# Web application

The interactive workspace is a Vite-built Svelte 5 single-page application using SvelteKit's static adapter.
Run it locally with `pnpm run web:dev`.
Vite proxies `/api`, `/auth`, `/health`, and `/public` to the local FastAPI process.
Browser requests use the generated API client and relative same-origin paths in production.

The public `/SKILL.md` endpoint serves the canonical external-agent instructions from `skills/polycolab/SKILL.md`.
SvelteKit imports that source as raw Markdown and prerenders it into the web build.
FastAPI serves the built file anonymously with a Markdown content type and returns 404 if it is missing.
The Docker web build includes `skills/`.
Agent connections, the connection guide, and the API introduction link to this same resource.

The product navbar spans the viewport, with 16px horizontal padding on desktop and 10px on mobile, independently of the page content width.
A small mathematical superscript **α** at the upper right of the brand identifies alpha development.
It remains visible when compact layouts show only the brand mark.
Compact outlined Planned pills continue to identify individual unfinished capabilities.

The header uses `BrandWordmark.svelte` for typography, alpha styling and accessible development text, with compact rendering.
Documentation deliberately uses a separate, focused Zensical header rather than the application navigation.
The brand opens public search at `/`.

Primary navigation uses this order:

1. Library (`/library`).
2. Workspaces (`/workspaces` when signed in, `/workspaces?scope=public` otherwise).
3. Activity (`/activity`).
4. Chat (`/chat`).
5. Docs, which links to the documentation index.
   Its adjacent dropdown contains Getting started and Developers.
   All navbar menus (Docs, account and mobile navigation) leave page scrolling unlocked, so their triggers toggle them and outside clicks dismiss them.
   Explicit shared trigger styling also applies on the separately built Documentation pages.
   Library lists only human-admitted catalogue statements and links to `/library/{entry_id}` for the official formulation, assumptions, source and reported status.
   Catalogue admission is not independent peer review or proof verification.

The shared account menu displays the account name and username.
Its actions use this order:

1. Profile.
2. Your workspaces.
3. Settings.
4. Security.
5. Getting started.
6. Moderation.
7. Sign out.
   Mobile uses the same account actions in a scrollable menu constrained to the viewport.
   Agent connections remains accessible at `/agents` but is not in the account menu.
   The available identity response does not expose a moderation capability, so the existing Moderation link remains visible.
   Its page explains the restriction and the API authorizes writes.

Account entry links preserve a same-origin `returnTo` through sign-in/signup switches.
Successful local sign-in or registration returns to that page.
Provider flows receive the same destination in their existing state.
Direct account entry defaults to Workspaces.
External destinations and authentication loops fall back to Workspaces.
Protected pages also keep their inline authentication flow.

Account settings uses compact, borderless navigation and content columns with a Groseille active-section treatment.
Each content section has a visible heading with a horizontal divider beneath it.

Profile displays the current account name and username.
Password and authentication (`/settings/security`) offers the implemented email password-reset flow when email recovery is enabled for built-in authentication.
Otherwise it shows a disabled reset action and explains availability or identity-provider ownership.
Settings no longer includes Notifications.
Its former route shows the not-found page.

Account recovery retains its capability gate.
A divider separates personal settings from the Access group, which contains Password and authentication, API keys, and Model providers.
Their routes are `/settings/api-keys` and `/settings/model-providers`; legacy `/settings/agent-keys` and `/settings/providers` links redirect to these routes.
Model providers remains visible when agent execution is unavailable, with an explanation and disabled configuration action.
The functional provider interface still requires the agent-execution capability.
Settings actions, including recovery email verification/resending, API keys, and model providers, show dismissible success/error toasts without changing page or dialog layout. Loading failures retain inline retry controls.
Model providers uses the shared shadcn Table with name and endpoint, model, masked key preview, connection-test result, and row actions.
Search filters loaded providers by name, model, or endpoint; the footer shows matching and loaded counts and preserves pagination.
Settings heading actions use 6px button corners.

Catalogue reads and mutations follow the configured catalogue capability.
Signed-in Library readers use one **Add to Library** action at the right of the index heading.
It opens `/library/new`, where they choose a statement, question or definition and provide literature, an attributable human review, or both.
The form previews the entry before admission, preserves retry keys and opens the saved `/library/{entry_id}`.
Admission requires human authorization.
The older sourced-only form remains on the Commons compatibility page.

Library no longer exposes duplicate admission actions.
Library uses the shared discovery heading, toolbar, loading and empty states, and compact result rows.
The admission action sits opposite the title.
Search filters stack on narrow screens.
Library uses a semantic catalogue table with entry title/type, recorded status and last-updated date.
Supporting basis and content previews belong on the dedicated entry page.

Mobile keeps the entry and status columns.
Titles wrap as needed.
Rows have no excerpts or per-row action buttons.
Titles open `/library/{entry_id}` for the complete statement, assumptions, source, review, revision history and copy actions.
Exact revision URLs remain directly accessible.
**Copy to workspace** calls `POST /api/v1/workspace-copies`, creating an independent editable object and opening its workspace object page.

The copy retains the exact source revision as provenance.
It does not inherit Library admission or status.
Workspace creation and copying share one transaction and retry receipt.
Legacy reference pins remain available through existing APIs/routes, without a Library imports sidebar entry.
The member Workspaces page keeps the heading **Workspaces** for every category.
Its creation action and search use the same placement as Library, while the results use a distinct project-card grid.

Each card shows purpose, visibility, role and updated date.
The entire live card opens its workspace.
Cards use two columns on wide screens and tablets, and one on mobile.
Library retains its dense statement catalogue table.
Desktop category tabs become a select on mobile.
Search is explicitly submitted and query/category parameters survive reload.

Public workspace discovery uses the same Workspaces heading, search placement and responsive card grid as the member directory.
Both public and member search run on the server across names and descriptions, with member category filters applied before pagination.

Directory pages show at most 20 cards with Previous/Next controls.
Changing scope, query or category resets pagination.
Member categories and role/member-count metadata remain scoped to membership.
Member workspaces use `WorkspaceWorkbench`; visitors retain the public workspace
shell in `Project`. The member shell uses a fixed-width icon rail with accessible
labels and shared tooltips on hover or keyboard focus. The rail chooses a page
layout rather than creating a content tab. Project opens the overview with project
navigation and details on the left. Research objects, Map, and Activity share the
selection-panel layout: controls and guidance on the left, content in the center,
and selection details on the right. The shell uses one selection-panel configuration,
open/close handler, header, and content container for all three modes.
`WorkspaceSectionPanel` renders their mode-specific details.
Workspace restores the worktree panel, unified content tabs, and a right panel that
switches between Explorer, Source control, and Details. Open chats, research
objects, and file drafts remain mounted while another layout is selected.
Left and right panels resize with pointer or keyboard controls and can collapse.
Narrow screens expose navigation and the selected layout's panel in drawers.
The member shell has no full-width product header: the shared brand wordmark and
workspace name sit above the left panel. Collapsed panels reopen from the main
view's toolbar. Workspace chrome uses the shared Groseille sidebar/selection
colors and Canard tool/agent-status accents, with a white editing surface.

Workspace cards, section navigation and panel controls use the shared 16px Lucide outline style, with distinct icons for each section.

Map follows Overview.
One Research navigation item covers objects and their saved revisions.
Research record and References are hidden from project navigation. Existing direct
routes and saved data remain available.

Research objects prioritizes in-page search and a compact semantic table.
The columns show object titles, type, version (formatted as v1), last updated date, and a four-character object ID prefix.
Workspace Activity uses the same single-line density with submission number, contributor, type, change, version, and relative time.
Both use 7px vertical cell padding, 13px titles, and 12px metadata, with internal horizontal scrolling when needed.

Research object row clicks or keyboard-activated title buttons open the selection preview in the right panel (a drawer on mobile).
Activity selections also open details in the right panel (a drawer on mobile).
Contributor links remain independent.
Each Research objects row also has a Focus on map icon linking to `/map?object=<id>`.
After the map loads, this link selects the object and frames its local neighborhood.
Selected rows retain their brand tint on hover.

Research objects and Map reuse the same focused-object component: title, type and version header, same-tab open icon, clear control, and Body/Relationships tabs.
The Body tab renders the listed version as Markdown in a bordered box.

Research objects loads relationship data only when its Relationships tab opens.
Search changes and section changes clear selection.
Pagination preserves it.
Search results remain on the page and count matching objects, searching only current revisions.
The table keeps its column headers without a separate search-results heading.
Clearing search restores the object list.

Both views retain pagination.
Create object opens one modal form with these controls:

- An Object type selector: Problem, Claim, Attempt, or Proof sketch.
- Title and content.
- Collapsed optional context.
- Conditional relationship fields.
- A Cancel/Create object footer.
  Dismissing the modal retains the draft, Cancel clears it, and successful creation opens the object.
  Existing revision URLs still work.
  User-facing copy refers to research, objects, and revisions rather than records.

Member workspace root routes open New chat when the current member can write and
agent execution is enabled; otherwise they open Overview. The left panel lists Main
and named worktrees, with the current user's conversations nested underneath.
Left-panel titles follow the selected rail mode: Project stays Project when
opening Overview, Agent connect, or Settings. Main content titles follow the
selected page. Left-panel views share a 13px semibold header, a 28px minimum header height,
12px outer padding, and a 12px gap before content. The left panel omits the product wordmark and workspace name; project identity is
available in Overview. Overview shows the project name, description, and a compact
visibility/access line and no sidebar details card. Overview, Agent connect,
Settings, Research objects, Map, and Activity omit the main-panel title bar;
mobile navigation controls remain available. Research objects and Activity also omit duplicate page titles above their content controls.
In Research objects, the left panel holds the loaded object count (or matching search count) and Create object action.
Selecting a result opens its exact revision details in the right panel, or the tools drawer on mobile; the left panel stays on the list controls.
Search stays above the main results table, and creation opens the existing modal with its draft and permission checks.
New worktree creates a saved branch from Main; selecting a worktree switches
Explorer and protects unsaved file edits. The panel has no search or refresh
controls. Archived worktrees can be inspected and restored. Saved worktrees reuse
the existing task metadata and API bindings; these are branch-backed working
contexts, not persistent Git linked-worktree directories on the API host.
Session list/detail responses expose only the latest run ID, status,
and cancellation-request timestamp; session lists batch those summaries.

The unified tab strip opens chats, files, research objects, individual research
records, reviews, and diff views. Layout pages do not enter the tab strip, including
when restoring tabs saved by an older browser version. Closing the last content
tab leaves an empty center panel and retains the selected worktree; it does not
create a new chat or open Overview. The empty state survives reload and rail
navigation, and the tab-strip plus still opens a chat explicitly.
The tab-strip plus creates a conversation in the selected worktree. Each worktree
row also has a New conversation action. Main conversations have no task binding;
named worktrees use their existing saved-branch binding. These actions create independent draft tabs;
a draft query identifier keeps each composer distinct until it creates a session.
`WorkspacePage` keeps opened route components mounted behind inactive tabs;
`WorkspaceFiles` owns the shared file editor state. Chat drafts and object edits
report dirty state to the shell. Dirty closes ask before discarding; workspace
exit and browser unload also protect drafts. Route-backed tabs preserve query
parameters for their own content instead of reading the active page's query.
Layout preferences and validated route-tab URLs are stored per account and
workspace in local storage. Draft text, file content, file tabs, and diff tabs are
not persisted there. Closing a tab destroys its component and stream lifecycle;
inactive chat tabs pause their session event streams and run polling. Reactivating
a chat refreshes messages and runs, then resumes events from its retained cursor
without discarding its draft. Chat context controls are
moved into the active Details host by `chat-panel-portal`.

Agent connect opens a setup guide for the workspace.
It includes account key setup and copyable instructions containing the workspace URL and ID.
It also links to SKILL.md and external-agent documentation.
Visitors can read the guide.
It explains that keys follow account memberships and are not restricted to this workspace.

New chat keeps a compact Customize bar above the composer.
The message surface owns hover and focus emphasis independently of that bar.
Agent preset selection sits in the composer action row beside Send and uses a radio menu with agent versions and purpose descriptions.
New chat silently defaults to the first available gateway profile.

The anchored Customize popover presents a prototype-only context scope and response style and discloses the implemented Hosted Codex system-prompt customization.
Context scope and response style remain presentation state and are not submitted to the API.
The workspace uses shared heading sizes, 14px navigation/body text, 16px research prose and standard buttons.
The overview leads with the workspace name and description.
Members see visibility in the Project layout’s left panel; visitors see it in the right panel.
The main overview presents the project description as readable Markdown, with an explicit empty state.

The main overview contains no action buttons or editing links.
Navigation and Settings remain in the sidebars.
It contains no recent-object or activity lists and makes no activity request.
Changes remain in Activity.
Research creation stays on the research list.
The project details panel shows visibility, access, and archive status.

Other sections provide relevant guidance and links.
Activity shows the selected submission’s contributor, readable action, local timestamp, excerpt, and exact revision link.
Workspace navigation and context tools omit proposal review.
Verification jobs is also omitted from workspace navigation for now.
Existing direct routes and underlying services remain implemented.
Visitors can read the workspace map and search its Research records without signing in.

Public discovery accepts a workspace filter while retaining public visibility and moderation filters.
Member search still requires membership.
Visitors can read public objects and their history, discussion, relations and evidence within that shell.
Contribution and management controls follow membership and role permissions.
Existing cursor pagination is unchanged.
Member-workspace text filtering still covers only loaded pages.

Member workspace links use `/workspaces/{workspace_id}`.
`/projects` and its detail paths remain compatibility aliases.
Anonymous workspace browsing uses `/workspaces?scope=public` and `/workspaces/{workspace_id}`.

HTTP API paths retain `/api/v1/workspaces?scope=member` and `/api/v1/workspaces?scope=public`.
Workspaces is visible to anonymous and signed-in readers and retains its workspace breadcrumb behavior.
The API link opens `/docs/api`, which reuses the product navbar above an isolated Scalar frame served by FastAPI at `/api/reference/content`.
The mobile menu uses the same destination order.
The legacy `/api/reference` URL redirects to `/docs/api` under the same access policy.
The `/docs` landing page links to the first-use guide, user setup and developer guides, and API reference.

The legacy `/connect` route continues to show the connection guide.

Activity is visible in desktop and mobile navigation for anonymous and signed-in readers.
`/activity` and `/activity/recent` open Recent submissions.
`/activity/workspaces` opens Active workspaces.
These pages serve normally before any sign-in gate.

Recent submissions uses `/api/v1/activity?recent=true` through the shared generated client.
It shows the latest 500 visible research events across active public workspaces, newest first without a date cutoff.
The human/agent filter applies within that set.

Contribution types remain visible in the table, without a separate type filter.
Each page contains up to 50 single-line rows in a bordered table.
Labeled columns show permanent submission index, contributor, workspace, object type, submission, version and time.
Type uses the same colored object-kind labels as workspaces.
Submission combines a plain-language action (such as Created, Revised or Commented on) with the linked object title.

Submission timestamps use `YYYY-MM-DD HH:mm:ss` in the device time zone, detected after mount, with UTC as the fallback.
The column indicates local/UTC and its tooltip names the time zone.

The compact table uses 12px metadata, 13px titles and 7px vertical cell padding.
It has a flexible submission column and a 960px minimum width.
Small screens support horizontal scrolling.

The service allocates the index once across all research activity.
Filtering and pagination do not change it.
It is distinct from the object version.
Gaps can represent activity outside this public feed.
Migration numbers existing events by date and ID.
A compact legend identifies human/agent icons.

Previous/Next controls replace rows rather than appending.
On narrower screens, the table scrolls horizontally and truncates long titles.
The feed excludes private, archived, deleted and Library-only containers.
The Activity navigation no longer has a Planned badge.
Active workspaces retains its time-window filters and shows a matching compact bordered table with workspace names, contributor and submission counts, and local timestamps.
A muted segmented control switches between views, with a raised selected segment and matching icons.

Its filter sits inline on desktop and wraps below on narrow screens.
The page starts with the view switch and inline filter.
Its Activity heading is screen-reader-only.
It omits duplicate section headings, introductory copy and the refresh control.
Both views have loading, retry and empty states.
A typed `ActivitySource` maps generated API types to the UI.

Without a source, each view states it is not connected.
The shared **Preview with examples** control renders labelled fictional records and counts without fake research links.
URL parameters preserve the view, time window, actor and explicit example mode across reload and browser history.
The views normalize default and invalid values.
Legacy Activity paths redirect within the app to the corresponding view query.
Relative timestamps expose the exact date accessibly.

Example ordering is explicitly illustrative.
Fixtures never appear as live data.
Library and Workspaces remain direct destinations.
Commons is not a navigation group.
Internal scope names and `/commons` compatibility routes remain, with the latter labelled Public research in the interface.

All environments default to FastAPI's built-in HTTP-only cookie session provider with `AUTH_MODE=local`.
Cookies are Secure outside local development.
Operators may optionally configure direct Google and GitHub authorization-code sign-in alongside passwords.
FastAPI owns the provider secret, PKCE verifier, nonce, browser-bound single-use state, stable provider-subject mapping and resulting ordinary local session.
The browser receives only configured provider names and an authorization URL.
The built-in sign-in form always displays Google and GitHub alternatives below the password form.

Unconfigured providers link to the not-found page at `/404`, while configured providers start the authorization flow.
Social sign-in is unavailable until the first local administrator exists.
It never links identities by email/display name.
When no mapping exists, it creates only a passwordless non-admin account.
Explicit account linking requires a recent exact local session.
Unlinking cannot remove the last login method.

Built-in username/password registration is separately operator-selected as `closed` (default), `open`, or `invitation`.
FastAPI advertises and enforces the effective mode, requires a deployment-bootstrapped administrator and exact Origin, and creates only an ordinary account plus session.
Core registration collects no email or terms evidence and grants no workspace membership.

Operators deliver invitation codes.
The service stores only their digests.
Codes expire and permit only one use.
The browser must use the exact contract in [the API documentation](api.md#built-in-registration-browser-contract).
It must clear prior private state on success.
It must keep social sign-in and OIDC entry distinct.

Operators may instead select `AUTH_MODE=oidc` for the separate provider-neutral organizational OIDC authorization-code flow with PKCE.
The browser obtains a short-lived bearer token through the configured OIDC adapter, and FastAPI verifies issuer, JWKS, audience, expiry, and subject.
OIDC mode disables direct Google/GitHub social routes.

Configure OIDC deployments with `OIDC_ISSUER`, `OIDC_JWKS_URL`, `OIDC_CLIENT_ID`, and `OIDC_AUDIENCE`.
The client ID is public browser metadata.
The browser never receives or stores an OIDC client secret.

The [API contract](api.md#built-in-social-auth-browser-contract) documents direct social authentication in the browser.
Browser controls use configured provider availability.
Live-provider consent and deployment acceptance require separate verification.

Public and private workspaces use the same Svelte routes and generated API contract.
Anonymous reads use permission-filtered public projections.
Membership and ownership govern private reads and writes.
FastAPI serves the Vite bundle and SPA fallback in production.
Library and public research pages require JavaScript but do not require a member session.

## Frontend migration

Production routes now use a Svelte shell with Tailwind styling and independently loaded research, graph, session, review, and settings views.
The workspace retains the original three-pane research room: session navigation, central work surface, and contextual tools.
Panels support resizing and collapse, with dialogs on mobile.

Navigation defaults to a fixed 280px width.
After navigation and dividers, the center and right Panel share the remaining width 60/40.
Resizing the right divider changes its share (20–60%) and preserves that ratio across browser resizing.
Collapsed rails remain 64px.

Graphs use Svelte Flow and open with all accessible workspace objects, including isolated objects.
The map loads paginated objects and relations with at most four concurrent object traversals, deduplicates relations, and includes referenced historical workspace revisions.
External revision connections remain in the readable relationship list.
Maps over 50 revisions use a canvas overview.
Smaller maps use compact rounded rectangles with a type badge and title, side connection points, and brand-colored selection.
Long titles truncate with a full-title tooltip.

Type badges share distinct icons, explicit labels, and subtle palette colors across map nodes, object cards, and the right Panel.
Type color is separate from the brand selection border and does not indicate verification status.
Revision details remain in the right Panel.
Workspace Activity uses compact bordered rows with permanent submission numbers, contributors, object types, readable actions, exact revision links, and device-local timestamps with a UTC fallback.
Selecting a submission number opens its details.
Workspace activity retains its existing 30-day scope and pagination.

Directed edges connect node boundaries with arrowheads at the target.
Interactive nodes use flat pale type fills, thin borders, and up to two lines of 13px title text.
Neutral one-pixel connections use small arrowheads and show labels only on hover or focus.
Direct connections turn brand red when focused while other connections fade.
The red outer focus ring and its gap preserve object type colors.
Parallel and reciprocal relationships use separate curves.

Dependency A → B means A depends on B.
“Focused object” searches titles, content, kinds, and IDs with multiple terms, quoted phrases, and exclusions.
Focus highlights connections and shows the object in the right Panel.
The center keeps the full-height graph followed by “Focused object” search and an always-visible “All objects” card list.
Entire cards select an object.
White cards sit on a muted surface and the focused card uses the brand-soft background, brand border, and an explicit Focused checkmark.

The right column uses “Right Panel” as its title when nothing is selected, and “Focused Object” for a map selection.
Its header has compact spacing and a prominent focused-object name.
The relationship link icon differs from the Map icon.
With no selection it shows “No object focused” and a prompt, with no relationships section.
After selection it shows the selected object with Body and Relationships information tabs, including on mobile.

Map selections and dedicated object pages reuse the compact object header, type cue, #version, and Body/Relationships inspector.
Relationship data for dedicated objects loads when its tab opens.
The same named relationship cards appear in the dedicated object’s Relationships view, filtered to the viewed revision.

Body is the initial tab and renders the current revision with the shared Markdown/math renderer.
The selected tab persists when changing objects.
Its collapsed rail provides an inspect icon.

With a query, the compact object list uses Search results for its heading and count.
It stays filtered after selection.
“Find object” scrolls to and focuses search.
“Clear search” restores the full list.

“Fit all” frames the graph.
“Center focused object” frames the selected object and its one-hop neighborhood.
Both renderers share viewport calculations with 15% padding on each side.
The focus stays centered.

Zoom ranges from 65% to 100%, with a 90% default for isolated objects.
Very small viewports can reduce the zoom further to fit the selected node.
Distant neighbors may be clipped to preserve readability.

Selecting an object preserves the map viewport.
Resizing fits the graph.
Reduced-motion preferences suppress viewport animation.
The dense canvas supports the same fit/center actions.

Relationship cards group links by direction and type, such as Depends on / Used by.
Each card emphasizes the other object.
A disclosure shows exact source/target revision names and #version labels.

Relationship cards use shared object-kind badges and neutral title links.
Unavailable external endpoints have a readable fallback.
Search syntax is available from the input tooltip and its accessible description.
Public visitors use public read projections.
The generated client remains the API boundary.
Query caching is in memory.

Account changes clear cached research and drafts.
Drafts survive internal navigation, not a browser reload.

The browser application uses Svelte.
The retired `/demo`, `/workspaces/demo`, `/library/demo`, and `/profile/demo` routes and their child paths show the page-not-found view.
They do not load research data.
Library, scoped direct contributions, and human publication use the implemented backend services.
Optional hosted execution and verification retain separate capability gates.
See the [roadmap](../roadmap.md) for remaining work and acceptance requirements.

Build output remains `src/web/dist`.
`index.html` is the SPA fallback and `/_app` serves Svelte assets with real missing-file responses.
Anonymous research uses the same application routes and API resources as signed-in readers.
`/workspaces?scope=public` browses public investigations.
Workspace detail URLs select member controls only after an authorized membership read.
Standalone public HTML handlers and `/public/*` URLs are removed.

## Public documentation authoring

Public guides live in `docs-site/docs/` as Python Markdown.
Zensical reads the MkDocs-compatible `docs-site/mkdocs.yml` and owns the documentation navigation, heading outline, search, code highlighting and theme controls.
A MiniJinja theme override supplies a focused documentation header.
The shared Svelte `ProductHeader` and its authentication adapter are not used by the documentation site.

The focused header places the Polycolab home link, search and theme controls in its first row.
A visually quieter second row contains guide tabs with text-aligned active underlines.
On desktop, the left rail keeps the current section title visible and marks the current page with an accent rule and stronger text.

The right heading outline is deliberately quieter and emphasizes only the current heading.
Mobile exposes the same page hierarchy through a drawer.
The theme maps its light and dark variants onto the shared production color tokens.
Canard is the documentation primary and link color.
Léman supplies suitable dark-mode and decorative accents.
Content cards retain Zensical's default surface colors.

Internal engineering documents remain under `docs/`.

Add guides beneath that content directory and to `nav` in `mkdocs.yml`.
Use Python-Markdown admonitions for notes.
The developer component gallery exercises configured components with Polycolab-specific examples:

- Cards, buttons, and details.
- Task lists, tables, and tabs.
- Highlighted and annotated code.
- Tooltips, footnotes, and captions.
- Icons and Mermaid diagrams.
  User research continues to use the application's sanitized Markdown renderer.

`pnpm run web:dev` starts a Zensical preview through the Vite plugin and proxies `/docs` to it.
Guide edits use Zensical's live reload.
`pnpm run web:build` builds Svelte, then builds Zensical inside `docs-site/site` and installs that generated tree into `src/web/dist/docs`.
FastAPI serves those static pages and assets from the same deployment, with 404s for missing documentation.
`/guide`, `/connect` and superseded guide paths redirect to their current documentation pages.
Zensical's `/docs/api/` page mounts Scalar inline with the checked-in OpenAPI snapshot and a static read-only configuration.

It therefore works in the Vite documentation preview without a running API while the backend still enforces the configured reference-access policy in production.
The reference and focused documentation header share the browser's native page scroll.
The API reference uses the ordinary Zensical page shell, including its native search, theme controls and mobile drawer.
Its loader removes Zensical's prose styling from the Scalar mount before initialization so Scalar retains its own presentation.
Zensical remains the mode authority: the loader initializes Scalar with the current mode and remounts it when that mode changes.
Both renderers map their framework-specific variables onto the color tokens owned by `src/web/src/styles/tokens.css`.

Service links to documentation use full page navigation.

The shared product header stays visible while scrolling on service pages.
The documentation header is independently sticky within the docs site.

Documentation uses normal document scrolling beneath its sticky header.
Print output hides the navigation chrome.

Service pages use a flex shell with the height of the viewport.
Content fills unused vertical space.
Thus, the footer reaches the bottom on short pages and follows content on long pages.

The footer shows About, Documentation, API reference, SKILL.md, Feedback / Report an issue and the configured build identifier.
These items share one compact row that wraps on narrow screens.
It omits the brand wordmark.

The footer shortens commit hashes in build identifiers.
It uses Local build as the fallback.
Feedback uses `VITE_FEEDBACK_URL`.
Without a configured destination it links to the generic `/404` page with a return-home link.

Footer links use compact 28px hit areas on desktop, expanding to 44px for touch and mobile, with visible keyboard focus.
The homepage introduction contains no additional links.

### Shared visual foundation

The frontend owns the framework-neutral color tokens in `src/web/src/styles/tokens.css`.
The documentation build copies that file into its generated styles.
The app maps Groseille to primary actions and Canard to research accents.
Documentation maps Canard to its primary role.
Accessible neutral, status, and dark-surface extensions supplement the six official EPFL colors.
The application theme continues to own typography and spacing, including a locally bundled Inter variable font.
Production controls use shadcn-svelte components in `src/web/src/lib/components/ui/`.

`src/web/components.json` selects the Lyra registry style: square control corners, compact text, and thin focus rings.
The application retains its shared color tokens and Inter font.
Tooltips retain their compact content and positioning, and vertical separators retain explicit full-height sizing.
`design-system.css` supplies their Tailwind utilities to SvelteKit.
Zensical's native components map their color variables to the shared tokens without loading the application design system.
Production forms, buttons, field labels, alerts, selection controls, menus, and modal surfaces use the shared registry components.
Specialized editor, graph, and pane-resizing behavior remains in the research components.

The web package pins the shadcn-svelte CLI as an exact development dependency, with its resolution in `pnpm-lock.yaml`.
From the repository root, use the installed CLI to add a component:

```sh
pnpm --filter @polycolab/web exec shadcn-svelte add <component>
```

The CLI reads the existing `components.json`; the application already has its initial configuration.
Component source is maintained locally, while behavior dependencies such as Bits UI receive package updates.
To refresh a component, preserve local changes in Git, run the same command with `--overwrite`, and review the diff to reconcile customizations.
The CLI version identifies the generator, not a fixed snapshot of the configured registry or the source of existing components.
See the [upstream CLI guide](https://www.shadcn-svelte.com/docs/cli) for supported commands.

### Global public search

The homepage `/` is the Home destination, with a spacious, centered Polycolab-alpha wordmark and rounded public search bar.
The clear-search button resets the query and result type, restores the homepage content and returns focus to the input.
Browser Back restores the previous search.

Below the search bar, a primary-colored Getting started button opens `/docs/getting-started/`.
SKILL.md opens the canonical external-agent skill file at `/SKILL.md`.
Chat with built-in agent is Planned and opens `/chat`.
A three-step introduction below covers starting with a question, collaborating in a public or private workspace, and optionally connecting an external agent.
Whitespace and a divider separate the introduction from the search area.

The former mission page is `/about`, linked from the footer.
The About page uses `About.svelte` for paragraph-based content without additional navigation links.
It uses the shared page heading and spacing with 14px body copy and a readable text width.

`/search` normalizes to `/` with replacement navigation.
The public GET form stores the query in `q` and result type in `type=all|research|workspaces`.
It supports reload/back navigation.
It accepts up to 200 characters, the narrower limit of the two existing search contracts.
The page calls public research discovery and public workspace search through the generated-client adapters.

Each result list has independent loading, retry and cursor pagination.
The page ignores late responses for replaced queries.
Library hits link to `/library`, other research hits to exact public record revisions, and workspace hits to public workspace pages.
Private research is not included.
A missing search endpoint shows a 404 message in its result section without hiding successful results from the other endpoint.
Other failures retain retry controls.

No new backend search or unified relevance ranking is claimed.
Research excerpts render complete Markdown blocks and KaTeX through the existing sanitized renderer.
The renderer highlights matching plain text without modifying math, links or code.
Result counts describe only loaded results.

### Planned hosted chat and capability labels

`/chat` is a public introductory preview, available without authentication and served normally by FastAPI.
The header orders Chat after Activity and marks Chat with a Planned badge on desktop and mobile.
The same badge identifies the unavailable session-management controls and pending canonical profile/agent attribution.
Working Search and external-agent connections are not marked planned.
The shared navigation uses a mobile menu below 900px.
Intermediate widths compact brand and account controls while retaining every research destination.

Workspace headers retain every primary navigation link in the same position as the workspace directory, with a separate, non-clickable workspace breadcrumb in the available space.
Docs retains its native search, compacted at intermediate widths.

Chat centers the conversation area with collapsed-by-default history and session setup panels.
It previews starter prompts, a disabled composer, and harness/provider/model/role/context/destination concepts.
It collects no messages or credentials and makes no execution calls.
Working links lead to external-agent connections and public workspaces.
Copy distinguishes private conversation from explicitly saved public research.
General chat persistence, harness/model selection, tool execution and save/continue-in-workspace remain future work.

Execution also requires native acceptance.
This preview does not enable hosted execution.

### People directory preview

`/people` is an anonymous-accessible frontend directory preview, accessible by direct URL but omitted from desktop and mobile navigation.
Its default state says the directory is not connected.
Explicit example mode supports name/handle/interest search and public-profile/workspace inspection using fictional profiles and no real account data.
A side panel becomes full-width on mobile, handles profile loading and errors in place, closes with Escape and restores focus.
Query, selected profile and explicit example mode persist in the URL through reload and browser history.

`PeopleSource` is a frontend view boundary for later generated-client mapping.
It supports pagination, retry, and stale-query handling.
A separate `getProfile(id)` lookup lets a deep link work independently of loaded directory results.

Activity and People share preview notices and **Exit example preview** controls.
Chat uses the same availability treatment without fictional conversations.
There is no directory HTTP API yet.
Profile discoverability, stable attribution, public projection and moderation policy remain backend/product rollout work.

### Page identification and discovery layout

SPA titles identify each page as “Page · Polycolab”.
Results titles include the current query and update with browser history.
Documentation retains its own page-specific titles.
Search, Activity, People and Chat share content width, heading typography, description spacing and mobile padding through discovery-page styles.
Each keeps its own result, preview and interaction layouts.
Library and public/ signed-in workspace directories also use this heading rhythm.

Workspace category controls appear below the heading: category buttons above 700px and a dropdown at mobile widths.
Both controls share the same selection when resizing.
Loaded Library statements, workspaces and public research details supply their names as browser titles.
Working discovery pages use shared loading indicators and empty/error panels with retry or search recovery actions.
Public-directory retry preserves the applied query without a full reload.

Page and panel headings omit decorative eyebrow/kicker labels throughout the Svelte UI.
Authorship, artifact roles and exact-revision metadata remain as normal content.
Removing the decorative treatment does not remove those research details.

## Personal profile

`/profile` presents a researcher identity and public contribution history, without account management, private workspace or agent-connection shortcuts.
Settings remain available through the shared account menu.
Desktop uses a compact summary sidebar.
Mobile presents the feed before the summary.
The summary and type selector share six disjoint groups: research, proofs/sketches, attempts/counterexamples, formalizations, computations and discussions.
Counts cover loaded records, remain unavailable before a successful read, and never imply lifetime totals or verification.

`q`, `type`, `year` and `day` retain contribution search and calendar state through reload and browser history.
The yearly heatmap aggregates unique loaded revision creation timestamps into UTC days.
Selecting a populated day filters the feed.
Mobile provides a day selector and a horizontally scrollable calendar that opens near the latest loaded contribution.
The feed sorts loaded records newest first.
Heatmap totals and active days describe the selected year.

Blank cells mean no loaded records, not confirmed inactivity.
Loading additional history uses the same discovery cursor and updates both the heatmap and feed.
No complete event ledger, streak, or lifetime contribution total is implied.

Search covers loaded titles, Markdown bodies and source identifiers.
It does not perform an exhaustive account query.
Pagination can reveal additional matches, preserves filters and loaded results after failures, and deduplicates revision IDs.
Excerpts reuse sanitized Markdown/math rendering and timestamps provide relative and exact dates.

The existing discovery adapter still matches human records by exact display name.
A visible notice above the feed explains possible same-name attribution and the absence of agent contributions.
Canonical attribution, profile editing, bio, interests, complete contribution history and public profile links remain Planned.
The page uses existing profile endpoints and has no public sharing route.

## Agent API keys

The workspace **Agent connect** page at `/workspaces/{id}/agent-connect` opens the existing account key creation dialog in place.
It links to account-wide key settings.
It provides a copyable prompt with the deployment origin, canonical `/SKILL.md` URL, workspace ID, and workspace URL.
The prompt contains no key, treats the workspace name as data, and asks the agent to wait for a specific research task before writing.

Readable public workspaces expose the page to visitors with a sign-in link that returns to the same workspace.
Contribution still requires an active owner or contributor role.
The page makes clear that a key follows all current and future memberships, not just the workspace shown in the prompt.

Account Settings includes `/settings/api-keys` for named account-wide keys, repeatable secret reveal/copy, server policy/usage/expiry, and confirmed revocation.
A shared Settings heading spans the navigation and content.
The settings layout has a 1200px maximum width with a fixed 220px sidebar, 13px body text, and compact controls.
On narrow screens, navigation wraps above the content and keeps the Access heading visible.
The shadcn Table lists names, masked key prefixes, status, local creation and expiration dates/times, and row actions.
Key previews use the public credential ID portion of the token.
The browser fetches full secrets only on explicit reveal or copy.

A copy icon beside each masked prefix copies the full key without opening the dialog.
Legacy and revoked keys have this action disabled.
Search and status filters operate on loaded keys only.
The footer reports loaded and matching counts and preserves cursor-based Load more.
Creation opens a Dialog with explicit Library-contribution permission.
When no agents exist it shows Agent name directly.

Otherwise an Agent selector and separate Create new agent action let users retain an existing contribution identity.
The dialog shows newly created or explicitly revealed keys and clears the secret on close.
Owners can reveal non-revoked keys again from the row menu.
Older hash-only keys remain usable but require replacement to enable reveal.
Revocation uses a row menu and confirmation dialog.
Connection instructions are collapsed below the table.

`/agents` links to key settings and retains workspace run history.
The component holds the secret only in memory.
It clears the secret when the dialog closes or navigation/account changes.
See the [shared API contract](external-agent-api.md) for live membership reach, private shared research, immutable run destinations, and human-only boundaries.

Workspace cards show the current member count alongside the update date.
Member workspace API projections include an aggregate `member_count`.
Anonymous public projections omit it.

Workspace navigation includes Activity at `/workspaces/:id/activity`.
It uses the existing activity endpoint, which filters results by permission, workspace, and the last 30 days.
Visitors receive public reads, and members receive member reads.
The page shows research event titles, actors, actions, times and exact revision links, with refresh, retry and cursor pagination.
This is recent research activity, not a full workspace settings audit.

Workspace Overview uses a compact workspace header, visibility badge, Map and Activity shortcuts, and compact creation actions.
Its research cards show shared object-kind badges, revision numbers, Markdown/math previews and author/time metadata.
Research object routes retain their creation workflows.

Workspace maps use ELK.js layered layout with left-to-right direction, orthogonal edge routing and rounded SVG corners.
The map loads ELK on demand and runs it in a worker.
It terminates the worker after layout.

Layout includes disconnected and isolated revisions.
Cycles retain their original edge direction.
Both Svelte Flow and the dense canvas consume the same positions and routes.
Selection does not trigger layout.

Graph-data changes do.
Crossing minimization does not guarantee a crossing-free graph.

The workspace directory keeps Public and Yours scope links visible when signed out.
Yours shows a sign-in prompt in the directory and makes no member-list request.
The sign-in return URL preserves the member scope.

Workspace directory cards have a consistent 160px height, or 180px on mobile to fit wrapped metadata.
A 6px gap separates two-line titles from compact, muted, two-line descriptions.
Metadata aligns with the bottom of each card.
Visibility appears in the footer on every card.

The workspace directory labels member categories All / Owned / Shared / Archived.
The server offers these sort orders:

- Recently updated (default).
- Case-insensitive alphabetical ascending (↑ A–Z).
- Case-insensitive alphabetical descending (↓ Z–A).
- Search relevance: exact title, title prefix, title match, then description match.
  Recent updates resolve ties.
  Cursors are bound to the sort and filters.
  The API returns the total matching workspace count using the same visibility and category/search filters before pagination.
  Pages display ranges such as “1-20 of 146 workspaces”.
  Page changes show result ranges and return focus and scroll to the results heading.

Sorting resets to page one and persists in the URL.

Workspace scope switches preserve the submitted search, sort order, and member category, while resetting pagination.
The search field has a clear control, and searched result counts use “matches”.
During sorting, searching, and pagination within a scope, the previous cards and their corresponding counts remain visible.
An Updating indicator remains until the next result arrives.
The view disables pagination during that request.
Previous results are not carried between public and member scopes.

## Workspace file workbench

The member workbench's right panel switches between Explorer, Source control,
and Details. Explorer supplies filename filtering and collapsible folders;
Source control lists saved uncommitted changes and supplies full-diff commit review,
discard, history, and merge actions. Files open in the same middle tab strip as chats,
research objects, and pages. History and merge review open diff tabs.

`WorkspaceFiles` remains mounted for the member workspace, supplies editor and
navigator snippets to `WorkspaceWorkbench`, and owns separate in-memory file
drafts. Switching content tabs or collapsing tools preserves those drafts.
Worktree switches retain drafts and tabs separately. Dirty closes and workspace
exit ask before discarding.
Cmd/Ctrl+S saves the active file; Markdown preview and the enhanced source editor
remain available. No autosave or browser storage persists file content.

Main and named worktrees appear in the left panel. Conversations within a worktree
share its files and retain run serialization, while conversation content remains
private. Save persists uncommitted files; explicit commit review uses a saved-state
revision and confirms exclusion of any unsaved drafts. Merge and update actions
require clean source and target worktrees. The API owns persistent linked Git
checkouts; agent sandboxes remain disposable. Narrow screens use a right-hand
tools drawer and return to content after opening a file. Nonmembers retain their
public context panel and cannot access repository content.

Focused helper tests cover restored tab validation, query preservation, route
identity, and bounded local storage restoration. Session API/store tests cover
latest-run summaries, batching, and private requester access. These checks do not
establish real-service browser behavior or deployment verification for the new
shell. See [workspace files](workspace-files.md) for persistence and authority.
