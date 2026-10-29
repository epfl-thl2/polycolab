<script lang="ts">
  import { onDestroy, setContext, untrack } from 'svelte';
  import { beforeNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { provideChatDrafts } from '../../lib/chat-drafts.svelte';
  import { projectContext, explain } from '../../svelte-lib/context';
  import ProductHeader from '../../ui/ProductHeader.svelte';
  import FeedbackToast from '../../ui/FeedbackToast.svelte';
  import LoadingState from '../../ui/LoadingState.svelte';
  import ProjectOverview from './sections/ProjectOverview.svelte';
  import ProjectWorkbench from './ProjectWorkbench.svelte';
  import { projectDialogsKey, projectUtility, type ProjectUtility } from './project-dialogs';
  import { notificationProjectKey } from '../../svelte-lib/notifications.svelte';
  import ProjectUtilityDialogs from './components/ProjectUtilityDialogs.svelte';
  let utility = $state<ProjectUtility>();
  let returnFocus = $state<HTMLElement>();
  function openUtility(value: ProjectUtility) {
    if (!member || (value === 'settings' && $project.data?.current_user_role !== 'OWNER')) return;
    returnFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    utility = value;
  }
  setContext(projectDialogsKey, { open: openUtility });
  setContext(notificationProjectKey, () => projectId);
  const drafts = provideChatDrafts();
  onDestroy(() => drafts.clear());
  let { projectId, path }: { projectId: string; path: string } = $props();
  const { api, auth } = projectContext();
  const project = createQuery(
    toStore(() => ({
      queryKey: ['project', projectId],
      queryFn: () => api.getProject(projectId),
    })),
  );
  const member = $derived(auth.signedIn && Boolean($project.data?.current_user_role));
  beforeNavigate(({ to, cancel }) => {
    if (!member || !to) return;
    const selected = projectUtility(projectId, to.url.pathname);
    if (!selected || (selected === 'settings' && $project.data?.current_user_role !== 'OWNER'))
      return;
    cancel();
    openUtility(selected);
  });
  $effect(() => {
    const selected = projectUtility(projectId, page.url.pathname);
    if (
      member &&
      selected &&
      (selected !== 'settings' || $project.data?.current_user_role === 'OWNER')
    ) {
      untrack(() => openUtility(selected));
      void goto(`/projects/${projectId}/overview`, { replaceState: true });
    }
  });
</script>

<FeedbackToast
  message={$project.isRefetchError ? explain($project.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $project.refetch() }}
/>

<svelte:head><title>{$project.data?.name ?? 'Project'} · Polycolab</title></svelte:head>
{#if member && $project.data}
  {#if $project.data.workspace_mode === 'default'}
    {#await import('./DefaultWorkbench.svelte')}<LoadingState>Opening project…</LoadingState>
    {:then module}<module.default project={$project.data} {path} />{/await}
  {:else if $project.data.workspace_mode === 'linear'}
    {#await import('./LinearWorkbench.svelte')}<LoadingState>Opening project…</LoadingState>
    {:then module}<module.default project={$project.data} {path} />{/await}
  {:else}<ProjectWorkbench project={$project.data} {path} />{/if}
  <ProjectUtilityDialogs project={$project.data} bind:utility {returnFocus} />
{:else}
  <ProductHeader {auth} active="projects" />
  <main id="main" class="page" tabindex="-1">
    {#if $project.isPending}<LoadingState>Opening project…</LoadingState>
    {:else if $project.data}<ProjectOverview
        name={$project.data.name}
        description={$project.data.description}
        visibility={$project.data.visibility}
      />
      <p>Project files and conversations are available to members.</p>
    {:else}<h1>Project unavailable</h1>
      <p>{explain($project.error)}</p>
      <button type="button" onclick={() => $project.refetch()}>Retry</button>{/if}
  </main>
{/if}
