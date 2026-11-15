<script lang="ts">
  import { projectContext } from '../svelte-lib/context';
  import { createLibraryApi } from '../lib/library-api';
  import { accountHref } from '../lib/account-navigation';
  import LoadingState from './LoadingState.svelte';
  import LibraryList from './LibraryList.svelte';
  import LibraryDetail from './LibraryDetail.svelte';
  import LibraryEditor from './LibraryEditor.svelte';
  import NotFound from './NotFound.svelte';

  let { path, search = '' }: { path: string; search?: string } = $props();
  const { auth } = projectContext();
  const api = createLibraryApi({
    getAccessToken: auth.token,
    onUnauthorized: () => auth.expireSession(),
  });
  const detail = $derived(path.match(/^\/library\/items\/([^/]+)(?:\/versions\/([^/]+))?$/));
  const edit = $derived(path.match(/^\/library\/mine\/([^/]+)\/edit$/));
  const privatePage = $derived(
    path === '/library/new' || path === '/library/mine' || Boolean(edit),
  );
</script>

<svelte:head
  >{#if !detail}<title>Library · Polycolab</title>{/if}</svelte:head
>

<nav class="page library-tabs" aria-label="Library sections">
  <a href="/library" aria-current={!privatePage ? 'page' : undefined}>Library</a>
  <a
    href="/library/mine"
    aria-current={path.startsWith('/library/mine') || path === '/library/new' ? 'page' : undefined}
    >My library</a
  >
</nav>
{#if privatePage && !auth.loaded}
  <main id="main" class="page" tabindex="-1"><LoadingState>Checking account…</LoadingState></main>
{:else if privatePage && !auth.signedIn}
  <main id="main" class="page" tabindex="-1">
    <h1>Library</h1>
    <p>
      <a href={accountHref('signin', path + search)}>Sign in</a> to manage your items.
    </p>
  </main>
{:else if path === '/library' || path === '/library/mine'}
  <LibraryList {api} {search} mine={path === '/library/mine'} />
{:else if path === '/library/new' || edit}
  <LibraryEditor {api} itemId={edit?.[1]} />
{:else if detail}
  <LibraryDetail {api} itemId={detail[1]} versionId={detail[2]} />
{:else}
  <NotFound />
{/if}

<style>
  .library-tabs {
    display: flex;
    gap: 1.5rem;
    padding-bottom: 0;
  }
  .library-tabs a[aria-current] {
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 6px;
  }
</style>
