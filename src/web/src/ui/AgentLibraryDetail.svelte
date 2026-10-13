<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import { projectContext } from '../svelte-lib/context';
  import { accountHref } from '../lib/account-navigation';
  import {
    libraryError,
    type AgentLibraryApi,
    type LibraryPublic,
    type LibraryVersion,
  } from '../lib/agent-library-api';
  import LoadingState from './LoadingState.svelte';
  import Markdown from './Markdown.svelte';
  let { api, entryId, versionId }: { api: AgentLibraryApi; entryId: string; versionId?: string } =
    $props();
  const { auth } = projectContext();
  let item = $state<LibraryPublic>();
  let versions = $state<LibraryVersion[]>([]);
  let cursor = $state<string | null>();
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  let copyKey: string | undefined;
  const data = $derived(item?.version.content);
  const versionHref = $derived(
    item ? `/agents/library/${entryId}/versions/${item.version.id}` : '',
  );
  async function load() {
    busy = true;
    error = '';
    item = undefined;
    versions = [];
    try {
      item = await api.get(entryId, versionId);
      const history = await api.history(entryId);
      versions = history.items;
      cursor = history.next_cursor;
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  async function more() {
    busy = true;
    error = '';
    try {
      const history = await api.history(entryId, cursor ?? undefined);
      versions = [...versions, ...history.items];
      cursor = history.next_cursor;
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      message = 'Copied.';
    } catch {
      message = 'Copy failed. Select the content below and copy it manually.';
    }
  }
  async function makeCopy() {
    if (!item) return;
    busy = true;
    error = '';
    copyKey ??= crypto.randomUUID();
    try {
      const owned = await api.copy(entryId, item.version.id, copyKey);
      await goto(`/agents/yours/${owned.entry.id}/edit`);
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  onMount(() => void load());
</script>

<svelte:head><title>{data?.title ?? 'Agent library'} · Polycolab</title></svelte:head>
<main id="main" class="page narrow" tabindex="-1">
  <a href="/agents">Back to library</a>
  {#if busy}<LoadingState>Loading entry…</LoadingState>{/if}
  {#if error}<p role="alert">{error}</p>
    <Button onclick={load}>Reload entry</Button>{/if}
  {#if item && data}
    <p>{item.kind === 'PROMPT' ? 'Prompt' : item.kind === 'SKILL' ? 'Skill' : 'Plugin'}</p>
    <h1>{data.title}</h1>
    <p>{data.description}</p>
    <p>
      By <a href={`/profiles/${item.version.author_user_id}`}>{item.version.author_name}</a> ·
      Version {item.version.number} · {new Date(item.version.published_at).toLocaleDateString()}
    </p>
    <p>License: {data.license}</p>
    {#if item.source_version_id}<p>
        Copied from exact source version: <a
          href={`/agents/library/${item.source_entry_id}/versions/${item.source_version_id}`}
          >View original version</a
        >
      </p>{/if}
    {#if item.archived}<p role="status">
        This entry is archived. Existing published versions remain readable.
      </p>{/if}
    <div class="actions">
      {#if item.kind !== 'PLUGIN'}<Button onclick={() => copyText(data.content)}
          >{item.kind === 'PROMPT' ? 'Copy prompt' : 'Copy SKILL.md'}</Button
        >{/if}
      {#if item.kind === 'SKILL'}<a
          class={buttonVariants({ variant: 'outline' })}
          href={api.downloadHref(entryId, item.version.id)}
          data-sveltekit-reload>Download SKILL.md</a
        >{/if}
      {#if data.source_url}<a
          class={buttonVariants({ variant: 'outline' })}
          href={data.source_url}
          target="_blank"
          rel="noopener noreferrer"
          >{item.kind === 'PLUGIN' ? 'View plugin source' : 'View source'}</a
        >{/if}
      {#if auth.signedIn}<Button
          variant="outline"
          disabled={busy || item.archived}
          onclick={makeCopy}>Make a copy</Button
        >{:else}<a href={accountHref('signin', versionHref)}>Sign in to make a copy</a>{/if}
      <Button variant="ghost" onclick={() => copyText(new URL(versionHref, location.origin).href)}
        >Copy version link</Button
      >
    </div>
    {#if message}<p role="status">{message}</p>{/if}
    {#if data.runtime}<p>Target runtime: {data.runtime}</p>{/if}
    {#if data.source_reference}<p>Source version/reference: {data.source_reference}</p>{/if}
    {#if item.kind !== 'PLUGIN'}<h2>{item.kind === 'PROMPT' ? 'Prompt text' : 'SKILL.md'}</h2>
      <pre class="resource-content">{data.content}</pre>{:else}<p>
        This listing provides setup instructions for an external plugin. Installation is managed in
        its target runtime.
      </p>{/if}
    {#if data.instructions}<h2>
        {item.kind === 'PLUGIN' ? 'Setup instructions' : 'Usage instructions'}
      </h2>
      <Markdown content={data.instructions} />{/if}
    {#if data.tags?.length}<p>Tags: {data.tags.join(' · ')}</p>{/if}
    <h2>Published versions</h2>
    <ul>
      {#each versions as version (version.id)}<li>
          <a
            href={`/agents/library/${entryId}/versions/${version.id}`}
            aria-current={version.id === item.version.id ? 'page' : undefined}
            >Version {version.number} — {version.content.title}</a
          >
        </li>{/each}
    </ul>
    {#if cursor}<Button variant="outline" disabled={busy} onclick={more}>Load more versions</Button
      >{/if}
  {/if}
</main>

<style>
  main {
    overflow-wrap: anywhere;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 1.5rem 0;
    align-items: center;
  }
  .resource-content {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    padding: 1rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    font-size: 0.9rem;
  }
</style>
