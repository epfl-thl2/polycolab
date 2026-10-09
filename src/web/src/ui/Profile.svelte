<script lang="ts">
  import { onMount } from 'svelte';
  import type { ObjectVersion } from '../lib/research-api';
  import { activityView, type Activity } from '../lib/history-api';
  import { UserRound } from '@lucide/svelte';
  import ContributionHeatmap from './ContributionHeatmap.svelte';
  import { contributionDay, contributionDays, historyDateLabel } from '../lib/contribution-history';
  import PlannedBadge from './PlannedBadge.svelte';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  import SearchExcerpt from './SearchExcerpt.svelte';
  import HighlightedText from './HighlightedText.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import { Badge } from '../lib/components/ui/badge';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { explain, workspace } from '../svelte-lib/context';
  import { readProfile, profileQuery, type NavigateQuery } from '../lib/ui-location';
  import { profileGroups, profileKindLabels, matchesProfileGroup } from '../lib/profile-view';

  let {
    search = '',
    onNavigate,
    profileId,
    agent = false,
  }: {
    search?: string;
    onNavigate?: NavigateQuery;
    profileId?: string;
    agent?: boolean;
  } = $props();
  const urlState = $derived(readProfile(search));
  let query = $derived(urlState.query);
  let filter = $derived(urlState.type);
  let draft = $derived(query);
  let selectedDay = $derived(urlState.day);
  let historyYear = $derived(urlState.year ?? new Date().getUTCFullYear());
  const { auth, history, externalAgents } = workspace();
  let profile = $state<Awaited<ReturnType<typeof history.profile>>>();
  let attribution = $state<'all' | 'authored' | 'sponsored'>('all');
  type Contribution = {
    id: string;
    contribution_id?: string | null;
    record: Pick<ObjectVersion, 'kind' | 'created_at'> &
      Pick<ObjectVersion['content'], 'title' | 'content_md' | 'reported_outcome'> & {
        object_version_id: string;
      };
    catalogue_entry_id?: string | null;
    source_identifier?: string | null;
    source_version?: string | null;
    source_locator?: string | null;
    activity?: Activity;
  };
  type ContributionPage = { items: Contribution[]; next_cursor: string | null };
  const displayName = $derived(
    profile?.actor.display_name ?? (profileId ? 'Contributor profile' : auth.label),
  );
  const username = $derived(
    !profileId ? (auth.account?.username ?? auth.user?.profile.preferred_username) : undefined,
  );
  const initials = $derived(
    displayName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'U',
  );
  let page = $state<ContributionPage>();
  let busy = $state(false);
  let error = $state('');
  const contributions = $derived(
    (page?.items ?? []).toSorted(
      (a, b) =>
        (Date.parse(b.record.created_at ?? '') || 0) - (Date.parse(a.record.created_at ?? '') || 0),
    ),
  );
  const dailyCounts = $derived(contributionDays(contributions));
  const filteredContributions = $derived(
    contributions.filter(
      (item) =>
        (!selectedDay || contributionDay(item.record.created_at) === selectedDay) &&
        matchesProfileGroup(item.record.kind, filter) &&
        `${item.record.title} ${item.record.content_md ?? ''} ${item.source_identifier ?? ''}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
    ),
  );
  function update(next: Partial<typeof urlState>) {
    query = next.query ?? query;
    filter = next.type ?? filter;
    if ('day' in next) selectedDay = next.day;
    if ('year' in next) historyYear = next.year ?? new Date().getUTCFullYear();
    onNavigate?.(
      profileQuery({
        query,
        type: filter,
        day: selectedDay,
        year: historyYear === new Date().getUTCFullYear() && !selectedDay ? undefined : historyYear,
      }),
    );
  }
  function clearFilters() {
    draft = '';
    update({ query: '', type: 'all', day: undefined });
  }
  function recordUrl(item: Contribution) {
    if (item.activity) return activityView(item.activity).revisionHref;
    return item.catalogue_entry_id
      ? `/library/${item.catalogue_entry_id}`
      : `/commons/records/${item.record.object_version_id}`;
  }
  async function load(more = false) {
    if (busy) return;
    busy = true;
    error = '';
    try {
      const id = profileId ?? (await externalAgents.identity()).user_id;
      if (!id) throw new Error('Sign in to view your profile');
      const [details, events] = await Promise.all([
        history.profile(id, agent),
        history.activity(
          id,
          agent,
          more ? (page?.next_cursor ?? undefined) : undefined,
          attribution,
        ),
      ]);
      profile = details;
      const next: ContributionPage = {
        items: events.items.map((activity) => ({
          id: activity.id,
          contribution_id: activity.contribution_id,
          activity,
          record: {
            object_version_id: activity.object_version_id,
            kind: activity.object_kind as Contribution['record']['kind'],
            title: activity.title,
            created_at: activity.occurred_at,
            content_md: activity.excerpt_md ?? '',
            reported_outcome: null,
          },
        })),
        next_cursor: events.next_cursor ?? null,
      };
      page =
        more && page
          ? {
              ...next,
              items: [
                ...new Map([...page.items, ...next.items].map((item) => [item.id, item])).values(),
              ],
            }
          : next;
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  onMount(() => void load());
</script>

<main id="main" class="page account-page profile-page" tabindex="-1">
  <header class="profile-header">
    <div class="profile-identity">
      <div class="profile-avatar" aria-hidden="true">{initials}</div>
      <div class="profile-name">
        <h1>{displayName}</h1>
        <p>
          {#if username}<span>@{username}</span><span aria-hidden="true"> · </span>{/if}Public
          research
        </p>
      </div>
    </div>
  </header>

  <div class="profile-preview">
    <strong>Public contribution history</strong>
    <p>Research activity attributed to this contributor's stable identity.</p>
    {#if profile}
      <p>
        {profile.authored_contributions} authored contributions · {profile.sponsored_contributions}
        sponsored contributions
      </p>
      {#if profile.actor.sponsor_user_id}<p>
          Sponsored by <a href={`/profiles/${profile.actor.sponsor_user_id}`}>researcher</a>
        </p>{/if}
    {/if}
    {#if !agent}<nav aria-label="Contribution attribution">
        {#each ['all', 'authored', 'sponsored'] as value (value)}<Button
            variant="outline"
            disabled={busy}
            aria-pressed={attribution === value}
            onclick={() => {
              attribution = value as typeof attribution;
              page = undefined;
              void load();
            }}>{value}</Button
          >{/each}
      </nav>{/if}
  </div>

  <ContributionHeatmap
    counts={dailyCounts}
    year={historyYear}
    {selectedDay}
    loaded={Boolean(page)}
    {busy}
    hasMore={Boolean(page?.next_cursor)}
    onYear={(year) => update({ year, day: undefined })}
    onDay={(day) => update({ day: !day || selectedDay === day ? undefined : day })}
    onLoadMore={() => load(true)}
  />

  <div class="profile-layout">
    <section class="profile-contributions" aria-labelledby="contributions-title">
      <div class="profile-section-heading">
        <h2 id="contributions-title">Public contributions</h2>
        {#if page}<span class="profile-result-count" role="status"
            >{filteredContributions.length} of {contributions.length} loaded · Newest first</span
          >{/if}
      </div>
      <form
        class="profile-search"
        onsubmit={(event) => {
          event.preventDefault();
          update({ query: draft.trim().slice(0, 200) });
        }}
      >
        <label class="sr-only" for="profile-search">Search loaded contributions</label>
        <Input
          id="profile-search"
          type="search"
          placeholder="Search loaded contributions"
          maxlength={200}
          bind:value={draft}
        />
        <Button type="submit" variant="outline">Search</Button>
      </form>
      <div class="profile-filters">
        <label for="contribution-type">Type</label>
        <NativeSelect
          id="contribution-type"
          aria-label="Contribution type"
          value={filter}
          onchange={(event) => update({ type: event.currentTarget.value as typeof filter })}
        >
          <option value="all">All contributions</option>
          {#each profileGroups as group (group.id)}<option value={group.id}>{group.label}</option
            >{/each}
        </NativeSelect>
        {#if query || filter !== 'all' || selectedDay}<Button
            type="button"
            variant="ghost"
            onclick={clearFilters}>Clear filters</Button
          >{/if}
      </div>

      {#if selectedDay}<div class="profile-date-filter" role="status">
          <span>Contributions on <strong>{historyDateLabel(selectedDay)}</strong></span>
          <Button variant="ghost" size="sm" onclick={() => update({ day: undefined })}
            >Show all dates</Button
          >
        </div>{/if}

      {#if error}<DiscoveryState
          kind="error"
          level="h3"
          title="Could not load contributions"
          description={error}
        >
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onclick={() => load(Boolean(page?.next_cursor))}>Retry</Button
          >
        </DiscoveryState>{/if}
      <div class="profile-feed" aria-busy={busy}>
        {#if !page && !error}<LoadingState>Loading public contributions…</LoadingState>{/if}
        {#each filteredContributions as item (item.id)}
          <article class="profile-contribution-card">
            <div class="profile-record-meta">
              {#if item.activity}<span>{item.activity.action.replaceAll('.', ' ')}</span><a
                  href={activityView(item.activity).authorHref}
                  >{item.activity.actor.display_name}</a
                >{/if}
              <Badge variant="outline">{profileKindLabels[item.record.kind]}</Badge
              >{#if item.record.created_at}<RelativeTime value={item.record.created_at} />{/if}
            </div>
            <h3>
              <a href={recordUrl(item)}><HighlightedText text={item.record.title} {query} /></a>
            </h3>
            {#if item.record.content_md}<SearchExcerpt
                content={item.record.content_md}
                {query}
              />{/if}
            {#if item.record.reported_outcome}<p class="profile-outcome">
                Reported outcome: {item.record.reported_outcome.toLowerCase().replaceAll('_', ' ')}
              </p>{/if}
            {#if item.source_identifier}<p class="profile-source">
                Source: {item.source_identifier}{item.source_version
                  ? ` · ${item.source_version}`
                  : ''}{item.source_locator ? ` · ${item.source_locator}` : ''}
              </p>{/if}
          </article>
        {:else}
          {#if page && !error}<DiscoveryState
              level="h3"
              title={query || filter !== 'all' || selectedDay
                ? 'No matching loaded contributions'
                : 'No public contributions loaded'}
              description={page.next_cursor
                ? 'There may be matches on the next page. Load more contributions or change your filters.'
                : query || filter !== 'all' || selectedDay
                  ? 'Try another search or clear the filters to see all loaded work.'
                  : 'Public contributions by this identity will appear here.'}
            >
              {#if query || filter !== 'all' || selectedDay}<Button
                  type="button"
                  variant="outline"
                  onclick={clearFilters}>Show all contributions</Button
                >{/if}
            </DiscoveryState>{/if}
        {/each}
      </div>
      {#if page?.next_cursor}<Button
          type="button"
          variant="outline"
          disabled={busy}
          onclick={() => load(true)}
          >{busy ? 'Loading more contributions…' : 'Load more contributions'}</Button
        >
        <p class="profile-page-note">
          Search and counts cover loaded public contributions only.
        </p>{/if}
    </section>

    <aside class="profile-sidebar" aria-label="Profile overview">
      <section class="profile-summary" aria-labelledby="profile-summary-title">
        <h2 id="profile-summary-title">Contribution summary</h2>
        <p class="profile-total">
          <strong
            aria-label={page
              ? `${contributions.length} loaded contributions`
              : 'Contribution count unavailable'}>{page ? contributions.length : '—'}</strong
          ><span>public contributions loaded</span>
        </p>
        <nav class="profile-counts" aria-label="Filter by contribution type">
          {#each profileGroups as group (group.id)}
            <button
              type="button"
              class="profile-stat"
              aria-label={group.label}
              aria-pressed={filter === group.id}
              onclick={() => update({ type: group.id })}
            >
              <span>{group.label}</span><strong
                >{page
                  ? contributions.filter((item) => matchesProfileGroup(item.record.kind, group.id))
                      .length
                  : '—'}</strong
              >
            </button>
          {/each}
        </nav>
        <p class="profile-page-note">
          Type counts describe loaded activity entries. The calendar counts distinct contributions.
        </p>
      </section>
      <section class="profile-planned" aria-labelledby="public-profile-title">
        <div class="profile-planned-heading">
          <UserRound size={18} aria-hidden="true" />
          <h2 id="public-profile-title">Public profile</h2>
          <PlannedBadge />
        </div>
        <p>Bios and research interests are coming soon.</p>
        <p class="profile-page-note">
          Profile editing is planned. Public history is attributed to stable human and agent
          identities.
        </p>
      </section>
    </aside>
  </div>
</main>

<style>
  .profile-page {
    max-width: 1160px;
  }
  .profile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    margin-bottom: 28px;
  }
  .profile-identity {
    display: flex;
    align-items: center;
    gap: 20px;
    min-width: 0;
  }
  .profile-avatar {
    display: grid;
    place-items: center;
    width: 76px;
    height: 76px;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--brand-soft);
    color: var(--brand);
    font-size: 26px;
    font-weight: 650;
  }
  .profile-name {
    min-width: 0;
  }
  h1 {
    margin: 0 0 6px;
    overflow-wrap: anywhere;
  }
  .profile-name p {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0;
    color: var(--muted-foreground);
    font-size: 14px;
    overflow-wrap: anywhere;
  }
  .profile-preview {
    border-left: 2px solid var(--line);
    padding: 0 0 0 14px;
    margin-bottom: 32px;
    font-size: 13px;
    color: var(--muted-foreground);
    max-width: 78ch;
  }
  .profile-preview strong {
    color: var(--foreground);
  }
  .profile-preview p {
    margin: 4px 0 0;
    line-height: 1.6;
  }
  .profile-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    gap: 36px;
    align-items: start;
  }
  .profile-contributions,
  .profile-sidebar {
    min-width: 0;
    display: grid;
    gap: 18px;
  }
  .profile-section-heading {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  h2 {
    margin: 0;
    font-size: 18px;
    line-height: 1.4;
  }
  .profile-result-count,
  .profile-page-note {
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .profile-search {
    display: flex;
    gap: 8px;
  }
  .profile-search :global(input) {
    min-width: 0;
    flex: 1;
  }
  .profile-filters {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    flex-wrap: wrap;
  }
  .profile-filters :global(select) {
    width: auto;
    max-width: 100%;
  }
  .profile-date-filter {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    padding: 8px 12px;
    border-radius: 6px;
    background: var(--accent);
    font-size: 12px;
  }
  .profile-feed {
    display: grid;
  }
  .profile-contribution-card {
    padding: 22px 0;
    border-top: 1px solid var(--line);
    min-width: 0;
  }
  .profile-record-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  h3 {
    margin: 10px 0;
    font-size: 19px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  h3 a {
    color: var(--foreground);
    text-decoration: none;
  }
  h3 a:hover {
    color: var(--brand);
    text-decoration: underline;
  }
  .profile-outcome,
  .profile-source {
    margin: 10px 0 0;
    font-size: 12px;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .profile-summary,
  .profile-planned {
    padding: 20px;
    border: 1px solid var(--line);
    border-radius: 10px;
  }
  .profile-summary h2,
  .profile-planned h2 {
    font-size: 15px;
  }
  .profile-total {
    display: grid;
    gap: 3px;
    margin: 20px 0;
  }
  .profile-total strong {
    font-size: 32px;
    line-height: 1.2;
    font-weight: 600;
  }
  .profile-total span {
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .profile-counts {
    display: grid;
    gap: 2px;
    margin-inline: -8px;
  }
  .profile-stat {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    min-height: 36px;
    padding: 8px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    text-align: left;
    font-size: 13px;
    color: var(--muted-foreground);
    cursor: pointer;
  }
  .profile-stat:hover,
  .profile-stat[aria-pressed='true'] {
    background: var(--accent);
    color: var(--foreground);
  }
  .profile-stat:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: 3px;
  }
  .profile-stat[aria-pressed='true'] {
    box-shadow: inset 2px 0 var(--brand);
  }
  .profile-stat strong {
    font-variant-numeric: tabular-nums;
    color: var(--foreground);
  }
  .profile-page-note {
    margin: 14px 0 0;
    line-height: 1.6;
  }
  .profile-planned-heading {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .profile-planned > p:not(.profile-page-note) {
    color: var(--muted-foreground);
    font-size: 13px;
    line-height: 1.6;
    margin: 14px 0 0;
  }
  @media (max-width: 800px) {
    .profile-layout {
      grid-template-columns: minmax(0, 1fr);
      gap: 32px;
    }
    .profile-sidebar {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: start;
    }
    .profile-stat {
      min-height: 44px;
    }
  }
  @media (max-width: 540px) {
    .profile-header {
      flex-wrap: wrap;
      gap: 18px;
    }
    .profile-avatar {
      width: 56px;
      height: 56px;
      font-size: 20px;
    }
    .profile-identity {
      gap: 14px;
    }
    .profile-header h1 {
      font-size: 26px;
    }
    .profile-sidebar {
      grid-template-columns: minmax(0, 1fr);
    }
    .profile-contributions {
      gap: 14px;
    }
    .profile-preview {
      margin-bottom: 26px;
    }
    .profile-search :global(input),
    .profile-filters :global(select),
    .profile-search :global(button) {
      min-height: 44px;
    }
  }
</style>
