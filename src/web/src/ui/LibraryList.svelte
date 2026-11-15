<script lang="ts">
  import { untrack } from 'svelte';
  import { goto } from '$app/navigation';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { projectContext } from '../svelte-lib/context';
  import { accountHref } from '../lib/account-navigation';
  import {
    libraryError,
    type LibraryApi,
    type LibraryKind,
    type LibraryOwned,
    type LibraryPublic,
  } from '../lib/library-api';
  import LoadingState from './LoadingState.svelte';
  let { api, search, mine = false }: { api: LibraryApi; search: string; mine?: boolean } = $props();
  const { auth } = projectContext();
  let items = $state<(LibraryPublic | LibraryOwned)[]>([]);
  let cursor = $state<string | null>();
  let q = $state('');
  let kind = $state<LibraryKind | ''>('');
  let tag = $state('');
  let error = $state('');
  let busy = $state(false);
  let generation = 0;
  const base = $derived(mine ? '/library/mine' : '/library');
  const labels = { PROMPT: 'Prompt', SKILL: 'Skill', PLUGIN: 'Plugin' };
  async function load(more = false) {
    const current = ++generation;
    busy = true;
    error = '';
    try {
      const filters = {
        q,
        kind: kind || undefined,
        tag,
        cursor: more ? (cursor ?? undefined) : undefined,
      };
      const page = mine ? await api.mine(filters) : await api.list(filters);
      if (current !== generation) return;
      items = more ? [...items, ...page.items] : page.items;
      cursor = page.next_cursor;
    } catch (cause) {
      if (current === generation) error = libraryError(cause);
    } finally {
      if (current === generation) busy = false;
    }
  }
  $effect(() => {
    const params = new URLSearchParams(search);
    q = params.get('q') ?? '';
    tag = params.get('tag') ?? '';
    const type = params.get('kind');
    kind = type === 'PROMPT' || type === 'SKILL' || type === 'PLUGIN' ? type : '';
    items = [];
    cursor = null;
    untrack(() => void load());
  });
  function apply() {
    const params = new URLSearchParams();
    if (q.trim()) params.set('q', q.trim());
    if (kind) params.set('kind', kind);
    if (tag.trim()) params.set('tag', tag.trim());
    void goto(base + (params.size ? `?${params}` : ''));
  }
</script>

<main id="main" class="page" tabindex="-1">
  <div class="library-heading">
    <div>
      <h1>{mine ? 'Your library' : 'Agent library'}</h1>
      <p>Discover, use, and share prompts, skills, and plugins for your agents.</p>
    </div>
    <a
      class={buttonVariants()}
      href={auth.signedIn ? '/library/new' : accountHref('signin', '/library/new')}>Contribute</a
    >
  </div>
  <form
    class="library-filters"
    onsubmit={(event) => {
      event.preventDefault();
      apply();
    }}
  >
    <label
      >Search<Input
        bind:value={q}
        maxlength={200}
        placeholder="Search titles, descriptions, and tags"
      /></label
    >
    <label
      >Type<NativeSelect bind:value={kind}
        ><option value="">All</option><option value="PROMPT">Prompts</option><option value="SKILL"
          >Skills</option
        ><option value="PLUGIN">Plugins</option></NativeSelect
      ></label
    >
    <label>Tag<Input bind:value={tag} maxlength={64} placeholder="e.g. proof" /></label>
    <Button type="submit">Search</Button>
  </form>
  {#if error}<p role="alert">{error}</p>
    <Button onclick={() => load(Boolean(items.length))}>Retry</Button>{/if}
  {#if busy}<LoadingState>Loading items…</LoadingState>{/if}
  <div class="library-grid">
    {#each items as item ('item' in item ? item.item.id : item.id)}
      {@const own = 'item' in item ? item : undefined}
      {@const metadata = own?.item}
      {@const publicItem = 'version' in item ? item : undefined}
      {@const data = own?.draft ?? publicItem!.version.content}
      <article class="panel">
        <p class="item-type">{labels[metadata?.kind ?? publicItem!.kind]}</p>
        <h2>
          <a href={own ? `/library/mine/${own.item.id}/edit` : `/library/items/${publicItem!.id}`}
            >{data.title}</a
          >
        </h2>
        <p>{data.description}</p>
        {#if own}<p>
            {own.item.published_version_id
              ? 'Published · Private draft available'
              : 'Private draft'}{own.item.archived ? ' · Archived' : ''}{own.item.hidden
              ? ' · Hidden by moderator'
              : ''}
          </p>{:else if publicItem}<p>
            By {publicItem.version.author_name} · Version {publicItem.version.number}
          </p>{/if}
        {#if data.runtime}<p>Runtime: {data.runtime}</p>{/if}
        <p class="tags">{data.tags?.join(' · ')}</p>
      </article>
    {/each}
  </div>
  {#if !busy && !error && !items.length}<div class="panel">
      <h2>
        {q || kind || tag
          ? 'No matching items'
          : mine
            ? 'No items yet'
            : 'The library is ready for contributions'}
      </h2>
      <p>
        {mine
          ? 'Create a private draft or make a copy of a published item.'
          : 'Contribute a reusable prompt, a SKILL.md file, or an existing plugin with setup instructions.'}
      </p>
      <a href="/docs/agents/" data-sveltekit-reload>How to contribute</a>
    </div>{/if}
  {#if cursor}<Button disabled={busy} onclick={() => load(true)}>Load more items</Button>{/if}
</main>

<style>
  main {
    overflow-wrap: anywhere;
  }
  .library-heading {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
  }
  .library-filters {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 1rem;
    margin: 1.5rem 0;
  }
  .library-filters label:first-child {
    flex: 1;
    min-width: 200px;
  }
  .library-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
  }
  .library-grid h2 {
    font-size: 1.1rem;
  }
  .item-type,
  .tags {
    font-size: 0.85rem;
  }
</style>
