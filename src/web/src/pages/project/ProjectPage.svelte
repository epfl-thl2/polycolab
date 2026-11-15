<script lang="ts">
  import { chatDraftKey } from '../../lib/chat-drafts.svelte';
  import type { Project } from '../../lib/projects-api';
  import { canWriteProject } from '../../lib/access';
  import LoadingState from '../../ui/LoadingState.svelte';
  import ProjectOverview from './sections/ProjectOverview.svelte';
  let {
    project,
    href,
    active,
    onState,
    onCreated,
  }: {
    project: Project;
    href: string;
    active: boolean;
    onState: (state: { label?: string; dirty: boolean }) => void;
    onCreated: (id: string) => void;
  } = $props();
  const projectId = $derived(project.id);
  const routeUrl = $derived(new URL(href, 'http://project.local'));
  const section = $derived(routeUrl.pathname.split('/')[3] || 'overview');
  const selectedId = $derived(routeUrl.pathname.split('/')[4]);
  const canWrite = $derived(
    canWriteProject(project.current_user_role, Boolean(project.archived_at)),
  );
  const canManage = $derived(project.current_user_role === 'OWNER');
  $effect(() => onState({ dirty: false }));
</script>

{#if section === 'overview'}
  <ProjectOverview
    name={project.name}
    description={project.description}
    visibility={project.visibility}
    role={project.current_user_role}
  />
{:else if section === 'conversations'}
  {#if canWrite || (project.current_user_role && selectedId !== 'new')}{#await import('./sections/Conversations.svelte')}<LoadingState
      >
        Opening private conversations…
      </LoadingState>{:then module}{#key selectedId}<module.default
          {projectId}
          conversationId={selectedId === 'new' ? undefined : selectedId}
          worktreeId={selectedId === 'new'
            ? routeUrl.searchParams.get('worktree') || undefined
            : undefined}
          view={selectedId ? 'chat' : 'list'}
          isVisible={active}
          draftKey={chatDraftKey(projectId, href)}
          {onCreated}
        />{/key}{/await}{:else}<h1>Private conversations</h1>
    <p>Agent conversations are available to active editors and owners.</p>{/if}
{:else if section === 'agent-connect'}
  {#await import('./sections/ProjectAgentConnect.svelte')}<LoadingState
      >Loading connection guide…</LoadingState
    >
  {:then module}<module.default
      {projectId}
      projectName={project.name}
      signedIn={true}
      {canWrite}
    />{/await}
{:else if section === 'settings' && canManage}
  {#await import('./sections/Settings.svelte')}<LoadingState>
      Opening settings…
    </LoadingState>{:then module}<module.default {project} />{/await}
{:else}<h1>Page not found</h1>{/if}
