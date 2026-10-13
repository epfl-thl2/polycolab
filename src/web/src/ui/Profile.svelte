<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import type { ObjectVersion } from '../lib/research-api';
  import { activityView, type Activity } from '../lib/history-api';
  import { Bot } from '@lucide/svelte';
  import ContributionHeatmap from './ContributionHeatmap.svelte';
  import { contributionDay, contributionDays, historyDateLabel } from '../lib/contribution-history';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  import SearchExcerpt from './SearchExcerpt.svelte';
  import HighlightedText from './HighlightedText.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import { Badge } from '../lib/components/ui/badge';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { explain, projectContext } from '../svelte-lib/context';
  import { readProfile, profileQuery, type NavigateQuery } from '../lib/ui-location';
  import { profileGroups, profileKindLabels, matchesProfileGroup } from '../lib/profile-view';

  let {
    search = '',
    onNavigate,
    profileId,
    agent = false,
    isOwnProfile = false,
  }: {
    search?: string;
    onNavigate?: NavigateQuery;
    profileId: string;
    agent?: boolean;
    isOwnProfile?: boolean;
  } = $props();
  const urlState = $derived(readProfile(search));
  let query = $derived(urlState.query);
  let filter = $derived(urlState.type);
  let draft = $derived(query);
  let selectedDay = $derived(urlState.day);
  let historyYear = $derived(urlState.year ?? new Date().getUTCFullYear());
  const { auth, history } = projectContext();
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
    profile?.actor.display_name ?? (isOwnProfile ? auth.label : 'Contributor profile'),
  );
  const username = $derived(
    profile?.actor.username ?? (isOwnProfile ? auth.account?.username : undefined),
  );
  $effect(() => {
    if (!agent && profile?.actor.username && profileId !== profile.actor.username) {
      const canonicalQuery = profileQuery(readProfile(search));
      void goto(
        `/profile/${profile.actor.username}${canonicalQuery ? `?${canonicalQuery}` : ''}${location.hash}`,
        { replaceState: true },
      );
    }
  });
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
      const id = profileId;
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
  <div class="profile-layout">
    <aside class="profile-sidebar" aria-label="Profile overview">
      <header class="profile-identity">
        <div class="profile-avatar" aria-hidden="true">
          {#if agent}<Bot size={64} />{:else}{initials}{/if}
        </div>
        <div class="profile-name">
          <h1>{displayName}</h1>
          {#if username}<p class="profile-handle">@{username}</p>{/if}
          {#if agent}<p class="profile-role">Research agent</p>{/if}
        </div>
      </header>
      {#if profile}
        <dl class="profile-public-totals">
          <div>
            <dt>Authored contributions</dt>
            <dd>{profile.authored_contributions}</dd>
          </div>
          <div>
            <dt>Sponsored contributions</dt>
            <dd>{profile.sponsored_contributions}</dd>
          </div>
        </dl>
        {#if profile.actor.sponsor_username}<p class="profile-sponsor">
            Sponsored by
            <a href={`/profile/${profile.actor.sponsor_username}`}
              >@{profile.actor.sponsor_username}</a
            >
          </p>{/if}
      {/if}
    </aside>
    <div class="profile-content">
      <div class="profile-calendar">
        <ContributionHeatmap
          counts={dailyCounts}
          year={historyYear}
          {selectedDay}
          loaded={Boolean(page)}
          {busy}
          onYear={(year) => update({ year, day: undefined })}
          onDay={(day) => update({ day: !day || selectedDay === day ? undefined : day })}
        />
      </div>
      <section id="history" class="profile-contributions" aria-labelledby="contributions-title">
        <div class="profile-section-heading">
          <h2 id="contributions-title">Public contributions</h2>
          {#if page && (query || filter !== 'all' || selectedDay)}<span
              class="profile-result-count"
              role="status">{filteredContributions.length} matching</span
            >{/if}
        </div>
        {#if !agent && (contributions.length || (profile && profile.authored_contributions + profile.sponsored_contributions))}<nav
            class="profile-attribution"
            aria-label="Contribution attribution"
          >
            {#each [{ value: 'all', label: 'All' }, { value: 'authored', label: 'Authored' }, { value: 'sponsored', label: 'Sponsored agents' }] as option (option.value)}
              <Button
                variant="ghost"
                disabled={busy}
                aria-pressed={attribution === option.value}
                onclick={() => {
                  attribution = option.value as typeof attribution;
                  page = undefined;
                  void load();
                }}>{option.label}</Button
              >
            {/each}
          </nav>{/if}
        {#if contributions.length || query || filter !== 'all' || selectedDay}
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
              placeholder="Search contributions"
              maxlength={200}
              bind:value={draft}
            />
            <NativeSelect
              aria-label="Contribution type"
              value={filter}
              onchange={(event) => update({ type: event.currentTarget.value as typeof filter })}
            >
              <option value="all">All types</option>
              {#each profileGroups as group (group.id)}<option value={group.id}
                  >{group.label}</option
                >{/each}
            </NativeSelect>
            <Button type="submit" variant="outline">Search</Button>
            {#if query || filter !== 'all' || selectedDay}<Button
                type="button"
                variant="ghost"
                onclick={clearFilters}>Clear filters</Button
              >{/if}
          </form>
        {/if}

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
                {#if item.activity}<span>{activityView(item.activity).actionLabel}</span
                  >{#if item.activity.actor.kind === 'agent' || item.activity.actor.username !== username}<a
                      href={activityView(item.activity).authorHref}
                      >{item.activity.actor.display_name}</a
                    >{/if}{/if}
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
                  Reported outcome: {item.record.reported_outcome
                    .toLowerCase()
                    .replaceAll('_', ' ')}
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
                    : 'Public contributions will appear here.'}
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
          >{/if}
      </section>
    </div>
  </div>
</main>

<style>
  .profile-page {
    max-width: 1160px;
  }
  .profile-layout {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: 40px;
    align-items: start;
  }
  .profile-sidebar,
  .profile-content {
    min-width: 0;
  }
  .profile-content {
    display: grid;
    gap: 28px;
  }
  .profile-identity {
    display: grid;
    gap: 20px;
  }
  .profile-avatar {
    display: grid;
    place-items: center;
    width: 168px;
    height: 168px;
    border-radius: 50%;
    background: var(--brand-soft);
    color: var(--brand);
    font-size: 54px;
    font-weight: 500;
    letter-spacing: -2px;
  }
  h1 {
    margin: 0;
    font-size: 26px;
    line-height: 1.25;
    letter-spacing: -0.5px;
    overflow-wrap: anywhere;
  }
  .profile-handle {
    margin: 6px 0 0;
    color: var(--muted-foreground);
    font-size: 18px;
    overflow-wrap: anywhere;
  }
  .profile-role {
    color: var(--muted-foreground);
    font-size: 13px;
    margin: 12px 0 0;
  }
  .profile-public-totals {
    display: grid;
    gap: 10px;
    padding-top: 20px;
    margin: 24px 0 0;
    border-top: 1px solid var(--line);
  }
  .profile-public-totals > div {
    display: flex;
    flex-direction: row-reverse;
    justify-content: flex-end;
    align-items: baseline;
    gap: 8px;
  }
  dt {
    font-size: 12px;
    color: var(--muted-foreground);
  }
  dd {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .profile-sponsor {
    margin: 14px 0 0;
    font-size: 12px;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  .profile-sponsor a {
    color: var(--brand);
  }
  h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    line-height: 1.4;
  }
  .profile-section-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  .profile-calendar {
    min-width: 0;
  }
  .profile-calendar :global(.contribution-history) {
    margin-bottom: 0;
    padding: 18px;
    border-radius: 8px;
  }
  .profile-calendar :global(h2) {
    font-size: 16px;
  }
  .profile-contributions {
    display: grid;
    gap: 16px;
    min-width: 0;
    scroll-margin-top: 24px;
  }
  .profile-attribution {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--line);
    padding-bottom: 8px;
    flex-wrap: wrap;
  }
  .profile-attribution :global(button) {
    color: var(--muted-foreground);
  }
  .profile-attribution :global(button[aria-pressed='true']) {
    background: var(--accent);
    color: var(--foreground);
    font-weight: 600;
  }
  .profile-result-count {
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .profile-search {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .profile-search :global(input) {
    min-width: 160px;
    flex: 1;
  }
  .profile-search :global(select) {
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
    padding-left: 20px;
    border-left: 1px solid var(--line);
    margin-left: 5px;
  }
  .profile-contribution-card {
    position: relative;
    padding: 0 0 24px;
    min-width: 0;
  }
  .profile-contribution-card::before {
    content: '';
    position: absolute;
    width: 9px;
    height: 9px;
    border: 2px solid var(--background);
    border-radius: 50%;
    background: var(--muted-foreground);
    left: -25px;
    top: 5px;
  }
  .profile-contribution-card + .profile-contribution-card {
    border-top: 1px solid var(--line);
    padding-top: 20px;
  }
  .profile-contribution-card + .profile-contribution-card::before {
    top: 25px;
  }
  .profile-record-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .profile-record-meta a {
    color: inherit;
    text-decoration: none;
  }
  .profile-record-meta a:hover {
    text-decoration: underline;
  }
  h3 {
    margin: 10px 0;
    font-size: 17px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  h3 a {
    color: var(--brand);
    text-decoration: none;
  }
  h3 a:hover {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .profile-outcome,
  .profile-source {
    margin: 10px 0 0;
    font-size: 12px;
    color: var(--muted-foreground);
    overflow-wrap: anywhere;
  }
  @media (max-width: 900px) {
    .profile-layout {
      grid-template-columns: 200px minmax(0, 1fr);
      gap: 24px;
    }
    .profile-avatar {
      width: 144px;
      height: 144px;
      font-size: 48px;
    }
  }
  @media (max-width: 700px) {
    .profile-layout {
      grid-template-columns: minmax(0, 1fr);
      gap: 24px;
    }
    .profile-identity {
      display: flex;
      gap: 16px;
      align-items: center;
    }
    .profile-avatar {
      width: 64px;
      height: 64px;
      flex-shrink: 0;
      font-size: 24px;
      letter-spacing: -1px;
    }
    .profile-avatar :global(svg) {
      width: 32px;
      height: 32px;
    }
    h1 {
      font-size: 24px;
    }
    .profile-handle {
      font-size: 16px;
      margin-top: 3px;
    }
    .profile-public-totals {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 20px;
      padding-top: 14px;
      margin-top: 16px;
    }
    .profile-public-totals > div {
      gap: 6px;
    }
    .profile-attribution :global(button),
    .profile-search :global(input),
    .profile-search :global(button),
    .profile-search :global(select) {
      min-height: 44px;
    }
  }
  @media (max-width: 480px) {
    .profile-calendar :global(.contribution-history) {
      padding: 14px;
    }
    .profile-search :global(input) {
      flex-basis: 100%;
    }
    .profile-feed {
      padding-left: 15px;
    }
    .profile-contribution-card::before {
      left: -20px;
    }
  }
</style>
