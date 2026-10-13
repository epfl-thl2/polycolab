<script lang="ts">
  import { Capabilities } from '../svelte-lib/capabilities.svelte';
  import { createHistoryApi } from '../lib/history-api';
  import LoadingState from './LoadingState.svelte';
  import { onMount, setContext } from 'svelte';
  import { toStore } from 'svelte/store';
  import { goto } from '$app/navigation';
  import { accountReturnPath } from '../lib/account-navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { SvelteMap } from 'svelte/reactivity';
  import { Auth } from '../svelte-lib/auth.svelte';
  import { contextKey, type Draft } from '../svelte-lib/context';
  import { createResearchApi } from '../lib/research-api';
  import { createAgentSessionsApi } from '../lib/agent-sessions-api';
  import { createProposalApi } from '../lib/proposals-api';
  import SignIn from './SignIn.svelte';
  import NotFound from './NotFound.svelte';
  import { createCatalogueApi } from '../lib/catalogue-api';
  import { createRecordsApi } from '../lib/records-api';
  import { createCommunityApi } from '../lib/community-api';
  import { createResearchStructureApi } from '../lib/research-structure-api';
  import { createPublicationApi } from '../lib/publication-api';
  import { createRepositoryApi } from '../lib/repository-api';
  import { createProjectTasksApi } from '../lib/project-tasks-api';
  import { createArtifactApi } from '../lib/artifact-api';
  import { createVerificationApi } from '../lib/verification-api';
  import type { SourceRevisionDraft } from '../lib/verification-view';
  import { createExternalAgentApi } from '../lib/external-agent-api';
  import ProductHeader from './ProductHeader.svelte';
  import ProductFooter from './ProductFooter.svelte';
  import { readSearch, type NavigateQuery } from '../lib/ui-location';
  let {
    path,
    search = '',
    hash = '',
    onNavigate,
  }: { path: string; search?: string; hash?: string; onNavigate?: NavigateQuery } = $props();
  const searchState = $derived(readSearch(search));
  const returnTo = $derived(accountReturnPath(new URLSearchParams(search).get('returnTo')));
  const query = useQueryClient();
  const drafts = new SvelteMap<string, Draft>();
  const sourceDrafts = new SvelteMap<string, SourceRevisionDraft>();
  let accountEpoch = $state(0);
  const auth = new Auth(() => {
    query.clear();
    drafts.clear();
    sourceDrafts.clear();
    accountEpoch += 1;
  });
  const options = { getAccessToken: auth.token, onUnauthorized: () => auth.expireSession() };
  const history = createHistoryApi(options);
  const externalAgents = createExternalAgentApi(options);
  const capabilities = new Capabilities();
  setContext(contextKey, {
    capabilities,
    history,
    catalogue: createCatalogueApi(options),
    records: createRecordsApi(options),
    community: createCommunityApi(options),
    researchStructure: createResearchStructureApi(options),
    publication: createPublicationApi(options),
    artifacts: createArtifactApi(options),
    repository: createRepositoryApi(options),
    tasks: createProjectTasksApi(options),
    verification: createVerificationApi(options),
    externalAgents,
    auth,
    query,
    drafts,
    sourceDrafts,
    api: createResearchApi(options),
    agents: createAgentSessionsApi(options),
    proposals: createProposalApi(options),
  });
  onMount(() => {
    void auth.initialize();
    return () => auth.dispose();
  });
  $effect(() => {
    if (
      !path.startsWith('/docs') &&
      !capabilities.configuration &&
      !capabilities.loading &&
      !capabilities.error
    )
      void capabilities.load();
  });
  const projectId = $derived(path.match(/^\/projects\/([^/]+)/)?.[1]);
  const projectScope = $derived(
    new URLSearchParams(search).get('scope') ?? (auth.signedIn ? 'member' : 'public'),
  );
  const retiredPreview = $derived(
    /^\/(?:demo|(?:projects|library|profile)\/demo)(?:\/|$)/.test(path),
  );
  const view = $derived(
    retiredPreview
      ? 'missing'
      : path === '/chat'
        ? 'chat'
        : path === '/activity' || path === '/activity/recent' || path === '/activity/projects'
          ? 'activity'
          : path === '/search' || path === '/'
            ? 'search'
            : path === '/about'
              ? 'about'
              : path === '/library' || path.startsWith('/library/')
                ? 'library'
                : path === '/docs' || path.startsWith('/docs/')
                  ? 'docs'
                  : path === '/connect'
                    ? 'connect'
                    : path === '/agents'
                      ? 'external-agents'
                      : path === '/projects' && projectScope === 'public'
                        ? 'public-projects'
                        : path === '/guide'
                          ? 'guide'
                          : path === '/commons' || path.startsWith('/commons/')
                            ? 'commons'
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
                                  : path === '/profile' ||
                                      /^\/(?:profile|agent-profiles)\/[^/]+$/.test(path)
                                    ? 'profile'
                                    : path === '/moderation'
                                      ? 'moderation'
                                      : path === '/settings' ||
                                          (path.startsWith('/settings/') &&
                                            path !== '/settings/notifications')
                                        ? 'account-settings'
                                        : projectId
                                          ? 'project'
                                          : path === '/projects'
                                            ? 'home'
                                            : 'missing',
  );
  const identity = createQuery(
    toStore(() => ({
      queryKey: ['current-profile-identity', accountEpoch],
      enabled:
        auth.loaded &&
        auth.signedIn &&
        (auth.configuration?.mode === 'oidc' ||
          (view === 'profile' && !path.startsWith('/agent-profiles/'))),
      retry: false,
      staleTime: Infinity,
      // Lazy account pages can mount after a fast identity failure.
      notifyOnChangeProps: 'all',
      queryFn: async () => {
        const user = await history.currentUser();
        if (!('username' in user) || (auth.configuration?.mode === 'local' && !user.username))
          throw new Error('The account service did not return a profile username.');
        return user;
      },
    })),
  );
  $effect(() => {
    if (auth.signedIn && $identity.data?.username) auth.username = $identity.data.username;
  });
  const pageTitle = $derived(
    view === 'search' && searchState.query
      ? `Results for “${searchState.query.slice(0, 200)}”`
      : {
          search: 'Home',
          chat: 'Chat',
          activity: 'Activity',
          about: 'About',
          library: 'Library',
          docs: 'Documentation',
          connect: 'Connect',
          guide: 'Getting started',
          'external-agents': 'Agent connections',
          'public-projects': 'Projects',
          commons: 'Public research',
          recovery: 'Account recovery',
          signin: 'Sign in',
          signup: 'Create account',
          profile: 'Profile',
          moderation: 'Moderation',
          'account-settings': 'Settings',
          project: 'Project',
          home: 'Projects',
          missing: 'Page not found',
        }[view],
  );
  const headerActive = $derived(
    view === 'chat'
      ? ('chat' as const)
      : view === 'search'
        ? ('search' as const)
        : path === '/activity' || path.startsWith('/activity/')
          ? ('activity' as const)
          : view === 'commons' || view === 'library'
            ? ('explore' as const)
            : view === 'docs' || view === 'connect' || view === 'guide'
              ? ('docs' as const)
              : view === 'external-agents'
                ? ('agents' as const)
                : view === 'profile'
                  ? ('profile' as const)
                  : view === 'moderation'
                    ? ('moderation' as const)
                    : view === 'account-settings'
                      ? ('settings' as const)
                      : view === 'home' || view === 'public-projects'
                        ? ('projects' as const)
                        : undefined,
  );
  $effect(() => {
    if (auth.loaded && auth.signedIn && (view === 'signin' || view === 'signup')) {
      if (/^\/docs(?:[/?#]|$)/.test(returnTo)) location.assign(returnTo);
      else void goto(returnTo, { replaceState: true });
    }
  });
</script>

<svelte:head
  >{#if view !== 'library' && view !== 'project'}<title>{pageTitle} · Polycolab</title
    >{/if}</svelte:head
>

<div class="product-shell" class:product-shell-project={view === 'project'}>
  <a class="skip-link" href="#main">Skip to content</a>
  {#if view !== 'docs' && view !== 'project'}<ProductHeader
      {auth}
      active={headerActive}
      currentPath={view === 'signin' || view === 'signup' ? returnTo : path + search}
    />{/if}
  <div class="product-shell-content">
    {#if capabilities.error}<div role="alert" class="notice">
        Application configuration could not be loaded. Optional actions are unavailable.
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
      {:else if view === 'chat'}
        {#await import('./Chat.svelte') then module}<module.default />{/await}
      {:else if view === 'activity'}
        {#await import('./Activity.svelte') then module}<module.default
            source={history.source}
            {search}
            {onNavigate}
          />{/await}
      {:else if view === 'search'}
        {#await import('./Search.svelte') then module}<module.default
            query={searchState.query}
            resultType={searchState.type}
            {onNavigate}
          />{/await}
      {:else if view === 'library'}
        {#await import('./Library.svelte') then module}{#key path}<module.default
              entryId={path.match(/^\/library\/([^/]+)/)?.[1]}
              revisionId={path.match(/^\/library\/[^/]+\/revisions\/([^/]+)/)?.[1]}
            />{/key}{/await}
      {:else if view === 'commons'}
        {#await import('./Commons.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Opening public research…</LoadingState>
          </main>
        {:then module}<module.default
            entryId={path.startsWith('/commons/records/') ||
            path.startsWith('/commons/publications/')
              ? undefined
              : path.match(/^\/commons\/([^/]+)/)?.[1]}
            revisionId={path.match(/^\/commons\/records\/([^/]+)/)?.[1]}
            publicationId={path.match(/^\/commons\/publications\/([^/]+)/)?.[1]}
          />{/await}
      {:else if path === '/projects' && !auth.loaded}
        <main id="main" class="page"><LoadingState>Opening projects…</LoadingState></main>
      {:else if path === '/projects'}
        {#await import('./Home.svelte') then module}<module.default
            publicScope={projectScope === 'public'}
          />{/await}
      {:else if view === 'project' && projectId}
        {#if !auth.loaded}<main id="main" class="page">
            <LoadingState>Opening project…</LoadingState>
          </main>
        {:else}{#await import('./ProjectRoute.svelte') then module}{#key projectId}<module.default
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
      {:else if view === 'external-agents' && auth.signedIn}
        {#await import('./ExternalAgents.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Opening agent connections…</LoadingState>
          </main>{:then module}<module.default />{/await}
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
      {:else if view === 'profile' && path !== '/profile'}
        {#if !auth.loaded}<main id="main" class="page" tabindex="-1">
            <LoadingState>Opening profile…</LoadingState>
          </main>
        {:else}{#await import('./Profile.svelte') then module}{#key path}<module.default
                {search}
                {onNavigate}
                profileId={path.split('/')[2]}
                agent={path.startsWith('/agent-profiles/')}
                isOwnProfile={auth.signedIn &&
                  $identity.data?.username === path.split('/')[2] &&
                  path.startsWith('/profile/')}
              />{/key}{/await}{/if}
      {:else if !auth.loaded}<main id="main" class="page narrow" tabindex="-1">
          <LoadingState>Opening your project…</LoadingState>
        </main>
      {:else if !auth.signedIn}<main id="main" class="page narrow" tabindex="-1">
          <SignIn {auth} returnTo={path + search + hash} />
        </main>
      {:else if view === 'profile'}
        {#await import('./ProfileRedirect.svelte') then module}<module.default
            {search}
            {hash}
            username={$identity.data?.username ?? undefined}
            error={$identity.error}
            onRetry={() => void $identity.refetch()}
          />{/await}
      {:else if view === 'moderation'}
        {#await import('./Moderation.svelte') then module}<module.default />{/await}
      {:else if view === 'home'}
        {#await import('./Home.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Loading projects…</LoadingState>
          </main>{:then module}<module.default />{/await}
      {:else if view === 'account-settings'}
        {#await import('./AccountSettings.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Loading settings…</LoadingState>
          </main>{:then module}<module.default {path} />{/await}
      {:else if projectId}
        {#await import('./Project.svelte')}<main id="main" class="page" tabindex="-1">
            <LoadingState>Opening research…</LoadingState>
          </main>{:then module}{#key projectId}<module.default {projectId} {path} />{/key}{/await}
      {:else}<main id="main" class="page" tabindex="-1">
          <h1>Page not found</h1>
          <p>This page does not exist or is not available yet.</p>
          <a href="/">Return home</a>
        </main>{/if}
    {/key}
  </div>
  {#if view !== 'project'}<ProductFooter />{/if}
</div>
