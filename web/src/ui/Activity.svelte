<script lang="ts">
  import PreviewNotice from './PreviewNotice.svelte';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import { readActivity, activityQuery, type NavigateQuery } from '../lib/ui-location';
  import { onMount, untrack } from 'svelte';
  import { deviceSubmissionClock, utcSubmissionClock } from '../lib/submission-time';
  let clock = $state(utcSubmissionClock);
  onMount(() => {
    clock = deviceSubmissionClock();
  });
  import { Bot, FolderOpen, ListOrdered, UserRound } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import { Badge } from '../lib/components/ui/badge';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import {
    activityKinds,
    activityWindows,
    type ActivitySource,
    type SubmissionView,
    type ActiveWorkspaceView,
  } from '../lib/activity-view';
  import { exampleActivitySource } from '../lib/activity-examples';

  let {
    source,
    search = '',
    onNavigate,
    initialView = 'recent',
  }: {
    source?: ActivitySource;
    search?: string;
    onNavigate?: NavigateQuery;
    initialView?: 'recent' | 'workspaces';
  } = $props();
  const urlState = $derived(readActivity(search));
  let view = $derived(search ? urlState.view : initialView);
  let window = $derived(urlState.window);
  let actor = $derived(urlState.actor);
  let kind = $derived(urlState.kind);
  let examples = $derived(urlState.examples);
  function update(patch: Partial<typeof urlState> = {}) {
    view = patch.view ?? view;
    window = patch.window ?? window;
    actor = patch.actor ?? actor;
    kind = patch.kind ?? kind;
    examples = patch.examples ?? examples;
    onNavigate?.(activityQuery({ view, window, actor, kind, examples }));
  }
  let submissions = $state<SubmissionView[]>([]);
  let workspaces = $state<ActiveWorkspaceView[]>([]);
  let cursor = $state<string>();
  let pageIndex = $state(0);
  let pageCursors = $state<(string | undefined)[]>([undefined]);
  let busy = $state(false);
  let error = $state('');
  let generation = 0;
  const activeSource = $derived(examples ? exampleActivitySource : source);
  async function load(more = false, targetPage = pageIndex) {
    if (!activeSource || busy) return;
    const request = generation;
    busy = true;
    error = '';
    try {
      if (view === 'recent') {
        const requestedPage = more ? pageIndex + 1 : targetPage;
        const requestedCursor = more ? cursor : pageCursors[requestedPage];
        const page = await activeSource.submissions({ window, actor, kind }, requestedCursor);
        if (request !== generation) return;
        submissions = page.items.slice(0, 50);
        pageIndex = requestedPage;
        pageCursors[requestedPage] = requestedCursor;
        cursor = requestedPage < 9 ? page.nextCursor : undefined;
      } else {
        const page = await activeSource.workspaces(window, more ? cursor : undefined);
        if (request !== generation) return;
        workspaces = more ? [...workspaces, ...page.items] : page.items;
        cursor = page.nextCursor;
      }
    } catch {
      if (request === generation) error = 'Activity could not be loaded. Please retry.';
    } finally {
      if (request === generation) busy = false;
    }
  }
  $effect(() => {
    void activeSource;
    void view;
    void window;
    if (view === 'recent') {
      void actor;
      void kind;
    }
    untrack(() => {
      generation += 1;
      submissions = [];
      workspaces = [];
      cursor = undefined;
      pageIndex = 0;
      pageCursors = [undefined];
      error = '';
      busy = false;
      void load();
    });
    return () => {
      generation += 1;
    };
  });
</script>

<main id="main" class="page discovery-page activity-page" tabindex="-1">
  <h1 class="sr-only">Activity</h1>
  {#if !source}<PreviewNotice
      message="Live activity is not available yet. Explore the planned views with examples."
      {examples}
      onToggle={() => update({ examples: !examples })}
    />{/if}
  {#if source && examples}<Button variant="outline" onclick={() => update({ examples: false })}
      >Exit example preview</Button
    >{/if}
  <div class="activity-toolbar">
    <nav class="activity-views" aria-label="Activity views">
      <Button
        variant="ghost"
        class="activity-view-button"
        aria-pressed={view === 'recent'}
        onclick={() => update({ view: 'recent' })}
        ><ListOrdered size={15} aria-hidden="true" />Recent submissions</Button
      >
      <Button
        variant="ghost"
        class="activity-view-button"
        aria-pressed={view === 'workspaces'}
        onclick={() => update({ view: 'workspaces' })}
        ><FolderOpen size={15} aria-hidden="true" />Active workspaces</Button
      >
    </nav>
    <div class="activity-filters">
      {#if view === 'workspaces'}<label
          >Time window<NativeSelect bind:value={window} onchange={() => update()}
            >{#each Object.entries(activityWindows) as [value, label] (value)}<option {value}
                >{label}</option
              >{/each}</NativeSelect
          ></label
        >
      {/if}
      {#if view === 'recent'}
        <label
          >Contributor<NativeSelect bind:value={actor} onchange={() => update()}
            ><option value="all">Humans and agents</option><option value="human">Humans</option
            ><option value="agent">Agents</option></NativeSelect
          ></label
        >
      {/if}
    </div>
  </div>
  <section
    aria-label={view === 'recent' ? 'Recent submissions' : 'Active workspaces'}
    aria-busy={busy}
  >
    {#if !activeSource}
      <div class="activity-empty">
        <h3>
          {view === 'recent'
            ? 'Recent submissions are coming soon'
            : 'Workspace activity is coming soon'}
        </h3>
        <p>
          {view === 'recent'
            ? 'This view will show saved research, versions, comments and evidence from humans and agents.'
            : 'This view will show recently active workspaces with contributor, submission, attempt and comment counts.'}
        </p>
        <a href="/workspaces?scope=public">Browse public workspaces</a>
      </div>
    {:else}
      {#if error}<div class="notice" role="alert">
          {error}<Button variant="outline" disabled={busy} onclick={() => load()}>Retry</Button>
        </div>{/if}
      {#if busy}<p role="status">Loading activity…</p>{/if}
      {#if view === 'recent'}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally.) -->
        <div
          class="submission-table-scroll"
          role="region"
          aria-label="Recent submissions table"
          tabindex="0"
        >
          <table>
            <caption class="sr-only">Recent submissions from public workspaces</caption>
            <colgroup>
              <col class="index-column" /><col class="author-column" /><col
                class="workspace-column"
              />
              <col class="type-column" /><col /><col class="version-column" /><col
                class="time-column"
              />
            </colgroup>
            <thead
              ><tr>
                <th scope="col">#</th><th scope="col">Contributor</th><th scope="col">Workspace</th>
                <th scope="col">Type</th><th scope="col">Submission</th><th scope="col">Version</th
                ><th scope="col" title={clock.timeZone}>Time ({clock.local ? 'local' : 'UTC'})</th>
              </tr></thead
            >
            <tbody>
              {#each submissions as item (item.id)}
                <tr class="submission-row">
                  <td class="submission-index">{item.submissionNumber ?? '—'}</td>
                  <td title={item.author}
                    ><span class="submission-author">
                      {#if item.actorKind === 'agent'}<Bot
                          size={14}
                          aria-label="Agent"
                        />{:else}<UserRound size={14} aria-label="Human" />{/if}
                      {#if item.authorHref}<a href={item.authorHref}>{item.author}</a>{:else}<span
                          >{item.author}</span
                        >{/if}
                    </span></td
                  >
                  <td title={item.workspace}>
                    {#if item.workspaceHref}<a href={item.workspaceHref}>{item.workspace}</a
                      >{:else}{item.workspace}{/if}
                  </td>
                  <td>
                    {#if item.objectKind}<ObjectKindBadge kind={item.objectKind} />{:else}<Badge
                        variant="outline">{activityKinds[item.kind]}</Badge
                      >{/if}
                  </td>
                  <td
                    ><div class="submission-description">
                      {#if item.actionLabel}<span class="submission-action">{item.actionLabel}</span
                        >{/if}
                      <h3 title={item.title}>
                        {#if item.revisionHref}<a href={item.revisionHref}>{item.title}</a
                          >{:else}{item.title}{/if}
                      </h3>
                    </div></td
                  >
                  <td>{item.revisionLabel}</td>
                  <td
                    ><time datetime={item.createdAt} title={item.createdAt}
                      >{clock.format(item.createdAt)}</time
                    ></td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="submission-legend" aria-label="Contributor legend">
          <span><UserRound size={14} aria-hidden="true" /> Human</span>
          <span><Bot size={14} aria-hidden="true" /> Agent</span>
        </div>
      {:else}
        {#if examples}<p class="muted">Illustrative order, not a live ranking</p>{/if}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally.) -->
        <div
          class="submission-table-scroll"
          role="region"
          aria-label="Active workspaces table"
          tabindex="0"
        >
          <table class="workspace-table">
            <caption class="sr-only">Active public workspaces</caption>
            <colgroup
              ><col /><col class="count-column" /><col class="count-column" /><col
                class="time-column"
              /></colgroup
            >
            <thead
              ><tr>
                <th scope="col">Workspace</th><th scope="col" class="numeric-cell">Contributors</th>
                <th scope="col" class="numeric-cell">Submissions</th>
                <th scope="col" title={clock.timeZone}
                  >Last submission ({clock.local ? 'local' : 'UTC'})</th
                >
              </tr></thead
            >
            <tbody>
              {#each workspaces as item (item.id)}
                <tr class="submission-row">
                  <td
                    ><h3
                      title={item.description ? `${item.name} — ${item.description}` : item.name}
                    >
                      {#if item.href}<a href={item.href}>{item.name}</a>{:else}{item.name}{/if}
                    </h3></td
                  >
                  <td class="numeric-cell">{item.contributors}</td>
                  <td class="numeric-cell">{item.submissions}</td>
                  <td
                    ><time datetime={item.lastActiveAt} title={item.lastActiveAt}
                      >{clock.format(item.lastActiveAt)}</time
                    ></td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
      {#if !busy && !error && !(view === 'recent' ? submissions.length : workspaces.length)}<div
          class="activity-empty"
        >
          <h3>No matching activity</h3>
          <p>Try a different time window or filter.</p>
        </div>{/if}
      {#if view === 'recent' && (submissions.length || pageIndex > 0)}
        <nav class="activity-pagination" aria-label="Submission pages">
          <Button
            variant="outline"
            disabled={busy || pageIndex === 0}
            onclick={() => load(false, pageIndex - 1)}>Previous</Button
          >
          <span
            >Page {pageIndex + 1} · {pageIndex * 50 + (submissions.length ? 1 : 0)}-{pageIndex *
              50 +
              submissions.length} shown</span
          >
          <Button variant="outline" disabled={busy || !cursor} onclick={() => load(true)}
            >Next</Button
          >
        </nav>
      {:else if cursor}<Button variant="outline" disabled={busy} onclick={() => load(true)}
          >Load more activity</Button
        >{/if}
    {/if}
  </section>
</main>

<style>
  section {
    min-width: 0;
    display: grid;
    gap: 12px;
  }
  h3,
  p {
    margin: 0;
  }
  h3 + p {
    margin-top: 0.5rem;
  }
  .activity-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px 20px;
  }
  .activity-views {
    display: flex;
    align-items: center;
    gap: 3px;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--muted);
  }
  .activity-views :global(.activity-view-button) {
    height: 32px;
    padding-inline: 10px;
    gap: 6px;
    border-radius: 7px;
    font-size: 13px;
    font-weight: 400;
    color: var(--muted-foreground);
    transition:
      background-color 160ms ease,
      color 160ms ease,
      box-shadow 160ms ease;
  }
  .activity-views :global(.activity-view-button[aria-pressed='true']) {
    background: var(--panel);
    color: var(--brand);
    box-shadow: 0 1px 3px var(--polycolab-shadow);
  }
  .activity-filters label {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--muted-foreground);
    font-size: 12px;
    white-space: nowrap;
  }
  .activity-filters :global(select) {
    width: 174px;
    font-size: 12px;
  }
  @media (prefers-reduced-motion: reduce) {
    .activity-views :global(.activity-view-button) {
      transition: none;
    }
  }
  .submission-table-scroll {
    min-width: 0;
    max-width: 100%;
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  .submission-table-scroll:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  table {
    width: 100%;
    min-width: 960px;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 12px;
  }
  .index-column {
    width: 64px;
  }
  .submission-index {
    font-variant-numeric: tabular-nums;
  }
  .type-column {
    width: 130px;
  }
  .version-column {
    width: 64px;
  }
  .workspace-column {
    width: 140px;
  }
  .author-column {
    width: 120px;
  }
  .time-column {
    width: 152px;
  }
  th,
  td {
    padding: 7px 8px;
    text-align: left;
    border-right: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  th {
    background: var(--muted);
    color: var(--muted-foreground);
    font-weight: 500;
  }
  th:last-child,
  td:last-child {
    border-right: 0;
  }
  tr:last-child td {
    border-bottom: 0;
  }
  .submission-row {
    white-space: nowrap;
  }
  .submission-row:hover {
    background: var(--muted);
  }
  td {
    color: var(--muted-foreground);
  }
  .submission-description {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
  }
  .submission-action {
    flex-shrink: 0;
    font-size: 12px;
  }
  td h3 {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 13px;
    font-weight: 400;
    color: var(--foreground);
  }
  .submission-author {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .submission-author :global(svg) {
    flex-shrink: 0;
  }
  .submission-author a,
  .submission-author > span {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .submission-legend {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 20px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .submission-legend > span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .activity-pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-size: 13px;
  }
  .workspace-table {
    min-width: 640px;
  }
  .workspace-table .time-column {
    width: 180px;
  }
  .count-column {
    width: 110px;
  }
  .numeric-cell {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .activity-empty {
    padding: 2rem;
    border: 1px dashed var(--line);
    border-radius: 0.75rem;
    display: grid;
    gap: 0.75rem;
  }
  @media (max-width: 600px) {
    .activity-filters {
      width: 100%;
    }
    .activity-filters label {
      justify-content: space-between;
    }
  }
</style>
