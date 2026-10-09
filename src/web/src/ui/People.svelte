<script lang="ts">
  import { untrack } from 'svelte';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Badge } from '../lib/components/ui/badge';
  import * as Sheet from '../lib/components/ui/sheet';
  import PlannedBadge from './PlannedBadge.svelte';
  import PreviewNotice from './PreviewNotice.svelte';
  import { readPeople, peopleQuery, type NavigateQuery } from '../lib/ui-location';
  import { examplePeopleSource, type PeopleSource, type PersonView } from '../lib/people-view';

  let {
    source,
    search = '',
    onNavigate,
  }: { source?: PeopleSource; search?: string; onNavigate?: NavigateQuery } = $props();
  const urlState = $derived(readPeople(search));
  let examples = $derived(urlState.examples);
  let query = $derived(urlState.query);
  let selected = $derived(urlState.profile);
  let draft = $derived(query);
  let people = $state<PersonView[]>([]);
  let cursor = $state<string>();
  let busy = $state(false);
  let error = $state('');
  let person = $state<PersonView>();
  let profileBusy = $state(false);
  let profileError = $state('');
  let profileRetry = $state(0);
  let profileTrigger: HTMLElement | undefined;
  let heading: HTMLHeadingElement;
  let generation = 0;
  const activeSource = $derived(examples ? examplePeopleSource : source);
  function update(next: Partial<typeof urlState>) {
    if ('query' in next) query = next.query ?? '';
    if ('profile' in next) selected = next.profile;
    examples = next.examples ?? examples;
    onNavigate?.(peopleQuery({ query, profile: selected, examples }));
  }
  async function load(more = false) {
    if (!activeSource || busy) return;
    const request = generation;
    busy = true;
    error = '';
    try {
      const page = await activeSource.search(query, more ? cursor : undefined);
      if (request !== generation) return;
      people = more ? [...people, ...page.items] : page.items;
      cursor = page.nextCursor;
    } catch {
      if (request === generation) error = 'People could not be loaded. Please retry.';
    } finally {
      if (request === generation) busy = false;
    }
  }
  $effect(() => {
    void activeSource;
    void query;
    untrack(() => {
      generation += 1;
      people = [];
      cursor = undefined;
      busy = false;
      error = '';
      void load();
    });
    return () => {
      generation += 1;
    };
  });
  $effect(() => {
    const id = selected;
    const current = activeSource;
    void profileRetry;
    let cancelled = false;
    person = undefined;
    profileError = '';
    profileBusy = false;
    if (id && current) {
      profileBusy = true;
      void current
        .getProfile(id)
        .then((value) => {
          if (!cancelled) {
            person = value;
            if (!value) profileError = 'This public profile is unavailable.';
          }
        })
        .catch(() => {
          if (!cancelled) profileError = 'This profile could not be loaded. Please retry.';
        })
        .finally(() => {
          if (!cancelled) profileBusy = false;
        });
    }
    return () => {
      cancelled = true;
    };
  });
</script>

<main id="main" class="page discovery-page people-page" tabindex="-1">
  <header class="discovery-heading">
    <div class="discovery-title">
      <h1 bind:this={heading} tabindex="-1">People</h1>
      {#if !source}<PlannedBadge />{/if}
    </div>
    <p>Find researchers, explore shared interests and get to know potential collaborators.</p>
  </header>
  {#if !source}<PreviewNotice
      message="The people directory is coming soon. Explore fictional profiles in the example preview."
      {examples}
      onToggle={() => update({ examples: !examples, profile: undefined })}
    />{/if}
  <form
    role="search"
    onsubmit={(event) => {
      event.preventDefault();
      const next = draft.trim();
      if (next === query) void load();
      else update({ query: next, profile: undefined });
    }}
  >
    <label for="people-search">Search people by name, handle or research interest</label>
    <div class="people-controls">
      <Input
        id="people-search"
        type="search"
        maxlength={200}
        bind:value={draft}
        placeholder="Name or research interest"
      /><Button type="submit" disabled={!activeSource}>Search people</Button>
    </div>
  </form>
  {#if !activeSource}<section class="people-empty">
      <h2>Public profiles are coming soon</h2>
      <p>
        Researchers will choose what to share about their interests and public work. Account and
        contact details will not be listed automatically.
      </p>
      <a href="/workspaces?scope=public">Meet collaborators through public workspaces</a>
    </section>
  {:else}
    {#if error}<div class="notice" role="alert">
        {error}<Button variant="outline" disabled={busy} onclick={() => load(Boolean(cursor))}
          >Retry</Button
        >
      </div>{/if}
    <p class:sr-only={!busy} role="status">
      {busy ? 'Finding people…' : `${people.length} profiles loaded.`}
    </p>
    <section aria-label="People results" aria-busy={busy}>
      <div class="people-grid">
        {#each people as item (item.id)}<article class="person-card">
            <div class="person-avatar" aria-hidden="true">
              {item.displayName
                .split(' ')
                .slice(0, 2)
                .map((part) => part[0])
                .join('')}
            </div>
            <h2>{item.displayName}</h2>
            <p class="muted">@{item.handle}</p>
            <p>{item.bio}</p>
            <div class="people-interests">
              {#each item.interests as interest (interest)}<Badge variant="outline"
                  >{interest}</Badge
                >{/each}
            </div>
            <Button
              variant="outline"
              aria-label={`View profile for ${item.displayName}`}
              aria-haspopup="dialog"
              onclick={(event) => {
                profileTrigger = event.currentTarget;
                update({ profile: item.id });
              }}>View profile</Button
            >
          </article>{/each}
      </div>
      {#if !busy && !error && !people.length}<div class="people-empty">
          <h2>No matching people</h2>
          <p>Try another name or research interest.</p>
        </div>{/if}
    </section>
    {#if cursor}<Button variant="outline" disabled={busy} onclick={() => load(true)}
        >Load more people</Button
      >{/if}
  {/if}
</main>

<Sheet.Root
  open={Boolean(selected)}
  onOpenChange={(open) => {
    if (!open) update({ profile: undefined });
  }}
>
  <Sheet.Content
    class="w-full! sm:max-w-xl! overflow-y-auto"
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      (profileTrigger?.isConnected ? profileTrigger : heading)?.focus({ preventScroll: true });
    }}
  >
    <Sheet.Header
      ><Sheet.Title>{person?.displayName ?? 'Public profile'}</Sheet.Title><Sheet.Description
        >{examples
          ? 'Fictional profile · example preview'
          : 'Public research and interests'}</Sheet.Description
      ></Sheet.Header
    >
    <div class="profile-content">
      {#if !activeSource}<p>Public profiles are coming soon. This profile is not available yet.</p>
      {:else if profileBusy}<p role="status">Loading profile…</p>
      {:else if profileError}<p role="alert">{profileError}</p>
        <Button variant="outline" onclick={() => (profileRetry += 1)}>Retry profile</Button>
      {:else if person}<p class="muted">@{person.handle}</p>
        <p>{person.bio}</p>
        <h2>Research interests</h2>
        <div class="people-interests">
          {#each person.interests as interest (interest)}<Badge variant="outline">{interest}</Badge
            >{/each}
        </div>
        <h2>Public workspaces</h2>
        <ul>
          {#each person.workspaces as workspace (workspace.name)}<li>
              {#if workspace.href}<a href={workspace.href}>{workspace.name}</a
                >{:else}{workspace.name}{/if}
            </li>{:else}<li>No public workspaces listed.</li>{/each}
        </ul>
        <h2>Public contributions</h2>
        {#if person.contributions?.length}<ul>
            {#each person.contributions as contribution (contribution.title)}<li>
                {#if contribution.href}<a href={contribution.href}>{contribution.title}</a
                  >{:else}{contribution.title}{/if}
                <p>{contribution.summary}</p>
              </li>{/each}
          </ul>{:else}<p>No public contribution summary is available.</p>{/if}
      {/if}
    </div>
  </Sheet.Content>
</Sheet.Root>

<style>
  .profile-content {
    display: grid;
    gap: 1.5rem;
  }
  .profile-content {
    padding: 0 1.5rem 2rem;
  }
  h2,
  p {
    margin: 0;
  }
  .people-interests,
  .people-controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .people-interests {
    flex-wrap: wrap;
  }
  form {
    display: grid;
    gap: 0.5rem;
  }
  .people-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
    gap: 1rem;
  }
  .person-card {
    border: 1px solid var(--line);
    border-radius: 0.75rem;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    align-items: start;
    gap: 0.75rem;
    overflow-wrap: anywhere;
  }
  .person-card h2,
  .profile-content h2 {
    font-size: 1.15rem;
  }
  .person-avatar {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: var(--muted);
    font-weight: 600;
  }
  .people-empty {
    padding: 2rem;
    border: 1px dashed var(--line);
    border-radius: 0.75rem;
    display: grid;
    gap: 0.75rem;
  }
</style>
