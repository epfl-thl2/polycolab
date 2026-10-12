<script lang="ts">
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { Bot, UserRound } from '@lucide/svelte';
  import { workspace, explain } from '../svelte-lib/context';
  import { activityView, type Activity } from '../lib/history-api';
  import { Button } from '../lib/components/ui/button';
  import * as Alert from '../lib/components/ui/alert';
  import LoadingState from './LoadingState.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  let {
    projectId,
    publicRead = false,
    selected = $bindable(),
    oninspect = () => {},
  }: {
    projectId: string;
    publicRead?: boolean;
    selected?: Activity;
    oninspect?: () => void;
  } = $props();
  const { history } = workspace();
  const activity = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['workspace-activity', projectId, publicRead],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        history.workspaceActivity(projectId, publicRead, pageParam),
      getNextPageParam: (page: Awaited<ReturnType<typeof history.workspaceActivity>>) =>
        page.next_cursor ?? undefined,
    })),
  );
  const events = $derived($activity.data?.pages.flatMap((page) => page.items) ?? []);
</script>

<header class="activity-heading">
  <p class="muted">Changes in this workspace · Last 30 days</p>
  <Button variant="ghost" disabled={$activity.isFetching} onclick={() => $activity.refetch()}
    >Refresh</Button
  >
</header>
{#if $activity.isPending}<LoadingState>Loading workspace activity…</LoadingState>{/if}
{#if $activity.isError}<Alert.Root variant="destructive" role="alert"
    >{explain($activity.error)}</Alert.Root
  ><Button
    variant="outline"
    onclick={() =>
      $activity.isFetchNextPageError ? $activity.fetchNextPage() : $activity.refetch()}
    >Retry activity</Button
  >{/if}
{#if events.length}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (keyboard access to horizontally scrollable table) -->
  <div
    class="activity-table workspace-data-table"
    role="region"
    aria-label="Workspace activity"
    tabindex="0"
  >
    <table aria-label="Workspace activity">
      <caption class="sr-only"
        >Workspace submissions. Select a change to inspect its details.</caption
      >
      <colgroup
        ><col style="width: 48px" /><col style="width: 110px" /><col style="width: 115px" /><col
        /><col style="width: 65px" /><col style="width: 100px" /></colgroup
      >
      <thead
        ><tr
          ><th scope="col">#</th><th scope="col">Contributor</th><th scope="col">Type</th><th
            scope="col">Change</th
          ><th scope="col">Version</th><th scope="col">When</th></tr
        ></thead
      >
      <tbody
        >{#each events as event (event.id)}{@const view = activityView(event)}
          <tr
            class:selected={selected?.id === event.id}
            onclick={(click) => {
              if ((click.target as HTMLElement).closest('a')) return;
              selected = event;
              oninspect();
            }}
          >
            <td class="table-metadata">{event.submission_number ?? '—'}</td>
            <td
              ><span class="contributor"
                >{#if event.actor.kind === 'agent'}<Bot
                    size={14}
                    aria-label="Agent"
                  />{:else}<UserRound size={14} aria-label="Human" />{/if}{#if view.authorHref}<a
                    href={view.authorHref}>{view.author}</a
                  >{:else}{view.author}{/if}</span
              ></td
            >
            <td><ObjectKindBadge kind={event.object_kind} /></td>
            <td class="submission"
              ><div class="change-inline">
                <span class="table-metadata">{view.actionLabel}</span><button
                  class="table-title"
                  aria-label={`Inspect submission ${event.submission_number ?? event.title}: ${event.title}`}
                  aria-pressed={selected?.id === event.id}
                  onclick={(click) => {
                    click.stopPropagation();
                    selected = event;
                    oninspect();
                  }}>{event.title}</button
                >
              </div></td
            >
            <td class="table-metadata"
              >{event.object_version_number ? `v${event.object_version_number}` : '—'}</td
            >
            <td class="event-time"><RelativeTime value={event.occurred_at} /></td>
          </tr>
        {/each}</tbody
      >
    </table>
  </div>
  <p class="table-hint">Select a change to see its details in the right panel.</p>
{:else if !$activity.isPending && !$activity.isError}<p class="muted">
    No research changes in the last 30 days.
  </p>{/if}
{#if $activity.hasNextPage}<Button
    variant="outline"
    disabled={$activity.isFetchingNextPage}
    onclick={() => $activity.fetchNextPage()}
    >{$activity.isFetchingNextPage ? 'Loading…' : 'Load more activity'}</Button
  >{/if}

<style>
  .activity-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  p {
    margin: 0;
    font-size: 13px;
  }
  .activity-table {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel);
  }
  .activity-table:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .submission {
    min-width: 160px;
  }
  .contributor {
    display: flex;
    align-items: center;
    gap: 6px;
    overflow: hidden;
    white-space: nowrap;
  }
  .contributor :global(svg) {
    flex-shrink: 0;
  }
  .change-inline {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
  }
  .change-inline .table-metadata {
    flex-shrink: 0;
  }
  .contributor a {
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--foreground);
    text-decoration: none;
  }
  .contributor a:hover {
    text-decoration: underline;
  }
  .event-time {
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .table-hint {
    margin: 8px 0 16px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
</style>
