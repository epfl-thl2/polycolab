<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import { toStore } from 'svelte/store';
  import { goto } from '$app/navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { Auth } from '../svelte-lib/auth.svelte';
  import { Capabilities } from '../svelte-lib/capabilities.svelte';
  import { notificationService } from '../svelte-lib/notifications.svelte';
  import { contextKey } from '../svelte-lib/context';
  import { accountReturnPath } from '../lib/account-navigation';
  import { createProjectsApi } from '../lib/projects-api';
  import { createAgentSessionsApi } from '../lib/agent-sessions-api';
  import { createExternalAgentApi } from '../lib/external-agent-api';
  import { createDocumentBuildsApi } from '../lib/document-builds-api';
  import { createRepositoryApi } from '../lib/repository-api';
  import { createProjectTasksApi } from '../lib/project-tasks-api';
  import { createArtifactApi } from '../lib/artifact-api';
  import LoadingState from './LoadingState.svelte';
  import SignIn from './SignIn.svelte';
  import NotFound from './NotFound.svelte';
  import ProductHeader from './ProductHeader.svelte';
  import ProductFooter from './ProductFooter.svelte';
  let {
    path,
    search = '',
    hash = '',
  }: {
    path: string;
    search?: string;
    hash?: string;
  } = $props();
  const notifications = notificationService();
  const query = useQueryClient();
  let accountEpoch = $state(0);
  const auth = new Auth(() => {
    notifications?.clear();
    query.clear();
    accountEpoch += 1;
  });
  const options = { getAccessToken: auth.token, onUnauthorized: () => auth.expireSession() };
  const api = createProjectsApi(options);
  const capabilities = new Capabilities();
  setContext(contextKey, {
    api,
    auth,
    query,
    capabilities,
    agents: createAgentSessionsApi(options),
    externalAgents: createExternalAgentApi(options),
    artifacts: createArtifactApi(options),
    repository: createRepositoryApi(options),
    tasks: createProjectTasksApi(options),
    documentBuilds: createDocumentBuildsApi(options),
  });
  onMount(() => {
    void auth.initialize();
    return () => auth.dispose();
  });
  $effect(() => {
    if (!capabilities.configuration && !capabilities.loading && !capabilities.error)
      void capabilities.load();
  });
  const returnTo = $derived(accountReturnPath(new URLSearchParams(search).get('returnTo')));
  const projectId = $derived(
    path.match(
      /^\/projects\/(?!demo(?:\/|$))([^/]+)(?:\/(?:overview|files|settings|agent-connect|sessions)(?:\/[^/]+)?)?\/?$/,
    )?.[1],
  );
  const projectScope = $derived(
    new URLSearchParams(search).get('scope') ?? (auth.signedIn ? 'member' : 'public'),
  );
  const view = $derived(
    path === '/' || path === '/projects'
      ? 'home'
      : projectId
        ? 'project'
        : path === '/about'
          ? 'about'
          : path === '/docs' || path.startsWith('/docs/')
            ? 'docs'
            : path === '/connect'
              ? 'connect'
              : path === '/guide'
                ? 'guide'
                : path === '/agents' || path.startsWith('/agents/')
                  ? 'agent-library'
                  : [
                        '/account/password-reset',
                        '/account/reset-password',
                        '/account/verify-email',
                        '/forgot-password',
                        '/reset-password',
                        '/verify-email',
                      ].includes(path)
                    ? 'recovery'
                    : path === '/signin'
                      ? 'signin'
                      : path === '/signup'
                        ? 'signup'
                        : path === '/settings' ||
                            (path.startsWith('/settings/') && path !== '/settings/notifications')
                          ? 'account-settings'
                          : 'missing',
  );
  const identity = createQuery(
    toStore(() => ({
      queryKey: ['current-profile-identity', accountEpoch],
      enabled: auth.loaded && auth.signedIn && auth.configuration?.mode === 'oidc',
      retry: false,
      staleTime: Infinity,
      notifyOnChangeProps: 'all' as const,
      queryFn: () => api.currentUser(),
    })),
  );
  $effect(() => {
    if (auth.signedIn && $identity.data?.username) auth.username = $identity.data.username;
  });
  $effect(() => {
    if (auth.loaded && auth.signedIn && (view === 'signin' || view === 'signup')) {
      if (/^\/docs(?:[/?#]|$)/.test(returnTo)) location.assign(returnTo);
      else void goto(returnTo, { replaceState: true });
    }
  });
  const headerActive = $derived(
    view === 'home'
      ? 'projects'
      : view === 'agent-library'
        ? 'agents'
        : view === 'account-settings'
          ? 'settings'
          : undefined,
  );
</script>

<svelte:head><title>Polycolab · Projects</title></svelte:head>
<div class="product-shell" class:product-shell-project={view === 'project'}>
  <a class="skip-link" href="#main">Skip to content</a>
  {#if view !== 'project' && view !== 'docs'}<ProductHeader
      {auth}
      active={headerActive}
      currentPath={path + search}
    />{/if}
  <div class="product-shell-content">
    {#if capabilities.error}<div role="alert" class="notice">
        Application configuration could not be loaded.
        <button type="button" onclick={() => capabilities.load()}>Retry configuration</button>
      </div>{/if}
    {#key accountEpoch}
      {#if auth.loaded && auth.signedIn && auth.configuration?.mode === 'oidc' && !$identity.data?.username}
        {#await import('./ChooseUsername.svelte') then module}<module.default
            error={$identity.error}
            loading={$identity.isPending}
            onRetry={() => void $identity.refetch()}
            onComplete={() => void $identity.refetch()}
          />{/await}
      {:else if view === 'home'}
        {#if !auth.loaded}<main id="main" class="page">
            <LoadingState>Opening projects…</LoadingState>
          </main>
        {:else}{#await import('./Home.svelte') then module}<module.default
              publicScope={projectScope === 'public'}
            />{/await}{/if}
      {:else if view === 'project' && projectId}
        {#if !auth.loaded}<main id="main" class="page">
            <LoadingState>Opening project…</LoadingState>
          </main>
        {:else}{#await import('../pages/project/Project.svelte') then module}{#key projectId}<module.default
                {projectId}
                {path}
              />{/key}{/await}{/if}
      {:else if view === 'about'}
        {#await import('./About.svelte')}<main
            id="main"
            class="page discovery-page about-page"
            tabindex="-1"
          >
            <LoadingState>Opening Polycolab…</LoadingState>
          </main>
        {:then module}<module.default />{/await}
      {:else if view === 'docs' || view === 'connect' || view === 'guide'}
        <main id="main" class="page" tabindex="-1">
          <a
            href={view === 'connect'
              ? '/docs/setup/external-agent/'
              : view === 'guide'
                ? '/docs/getting-started/'
                : path}
            data-sveltekit-reload>Open documentation</a
          >
        </main>
      {:else if view === 'agent-library'}
        {#key path + ':' + accountEpoch}
          {#await import('./Agents.svelte')}<main id="main" class="page" tabindex="-1">
              <LoadingState>Opening Agents…</LoadingState>
            </main>{:then module}<module.default {path} {search} />{/await}
        {/key}
      {:else if view === 'recovery'}
        {#if capabilities.enabled('email_recovery')}
          {#await import('./AccountRecovery.svelte') then module}<module.default
              mode={path.endsWith('/verify-email')
                ? 'verify'
                : path.endsWith('/reset-password')
                  ? 'confirm'
                  : 'request'}
            />{/await}
        {:else}<main id="main" class="page">
            <h1>Account recovery unavailable</h1>
            <p>Contact your deployment operator.</p>
          </main>{/if}
      {:else if view === 'signin' || view === 'signup'}
        {#if !auth.loaded}<main id="main" class="page narrow" tabindex="-1">
            <LoadingState>Opening account access…</LoadingState>
          </main>
        {:else}<main id="main" class="page narrow auth-page" tabindex="-1">
            <div class="auth-card">
              <SignIn {auth} {returnTo} mode={view === 'signup' ? 'signup' : 'signin'} />
            </div>
          </main>{/if}
      {:else if view === 'missing'}<NotFound />
      {:else if !auth.loaded}<main id="main" class="page">
          <LoadingState>Opening your account…</LoadingState>
        </main>
      {:else if !auth.signedIn}<main id="main" class="page narrow">
          <SignIn {auth} returnTo={path + search + hash} />
        </main>
      {:else if view === 'account-settings'}
        {#await import('./AccountSettings.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Loading settings…</LoadingState>
          </main>{:then module}<module.default {path} />{/await}
      {:else}<NotFound />{/if}
    {/key}
  </div>
  {#if view !== 'project'}<ProductFooter />{/if}
</div>
