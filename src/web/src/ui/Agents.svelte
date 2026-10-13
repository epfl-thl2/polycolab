<script lang="ts">
  import { projectContext } from '../svelte-lib/context';
  import { createAgentLibraryApi } from '../lib/agent-library-api';
  import { accountHref } from '../lib/account-navigation';
  import LoadingState from './LoadingState.svelte';
  import ExternalAgents from './ExternalAgents.svelte';
  import AgentLibraryList from './AgentLibraryList.svelte';
  import AgentLibraryDetail from './AgentLibraryDetail.svelte';
  import AgentLibraryEditor from './AgentLibraryEditor.svelte';
  import NotFound from './NotFound.svelte';

  let { path, search = '' }: { path: string; search?: string } = $props();
  const { auth } = projectContext();
  const api = createAgentLibraryApi({
    getAccessToken: auth.token,
    onUnauthorized: () => auth.expireSession(),
  });
  const detail = $derived(path.match(/^\/agents\/library\/([^/]+)(?:\/versions\/([^/]+))?$/));
  const edit = $derived(path.match(/^\/agents\/yours\/([^/]+)\/edit$/));
  const privatePage = $derived(
    path === '/agents/connections' ||
      path === '/agents/new' ||
      path === '/agents/yours' ||
      Boolean(edit),
  );
</script>

<svelte:head
  >{#if !detail}<title>Agents · Polycolab</title>{/if}</svelte:head
>

<nav class="page agents-tabs" aria-label="Agents sections">
  <a href="/agents" aria-current={!privatePage ? 'page' : undefined}>Library</a>
  <a
    href="/agents/yours"
    aria-current={path.startsWith('/agents/yours') || path === '/agents/new' ? 'page' : undefined}
    >Yours</a
  >
  <a href="/agents/connections" aria-current={path === '/agents/connections' ? 'page' : undefined}
    >Connections</a
  >
</nav>
{#if privatePage && !auth.loaded}
  <main id="main" class="page" tabindex="-1"><LoadingState>Checking account…</LoadingState></main>
{:else if privatePage && !auth.signedIn}
  <main id="main" class="page" tabindex="-1">
    <h1>Agents</h1>
    <p>
      <a href={accountHref('signin', path + search)}>Sign in</a> to manage your entries and connections.
    </p>
  </main>
{:else if path === '/agents/connections'}
  <ExternalAgents />
{:else if path === '/agents' || path === '/agents/library' || path === '/agents/yours'}
  <AgentLibraryList {api} {search} yours={path === '/agents/yours'} />
{:else if path === '/agents/new' || edit}
  <AgentLibraryEditor {api} entryId={edit?.[1]} />
{:else if detail}
  <AgentLibraryDetail {api} entryId={detail[1]} versionId={detail[2]} />
{:else}
  <NotFound />
{/if}

<style>
  .agents-tabs {
    display: flex;
    gap: 1.5rem;
    padding-bottom: 0;
  }
  .agents-tabs a[aria-current] {
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 6px;
  }
</style>
