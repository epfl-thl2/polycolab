<script lang="ts">
  import * as Dialog from '../../../lib/components/ui/dialog';
  import type { Project } from '../../../lib/projects-api';
  import { canWriteProject } from '../../../lib/access';
  import ProjectOverview from '../sections/ProjectOverview.svelte';
  import LoadingState from '../../../ui/LoadingState.svelte';
  import type { ProjectUtility } from '../project-dialogs';
  let {
    project,
    utility = $bindable(),
    returnFocus,
  }: {
    project: Project;
    utility?: ProjectUtility;
    returnFocus?: HTMLElement;
  } = $props();
  const settings = $derived(utility === 'settings');
</script>

<Dialog.Root
  open={Boolean(utility)}
  onOpenChange={(open) => {
    if (!open) utility = undefined;
  }}
>
  <Dialog.Content
    class="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-3xl"
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      if (returnFocus?.isConnected) returnFocus.focus();
      else document.querySelector<HTMLButtonElement>('[aria-label="Open navigation"]')?.focus();
    }}
  >
    <Dialog.Header class="shrink-0 pr-8">
      <Dialog.Title
        >{settings
          ? 'Project settings'
          : utility === 'information'
            ? 'Project information'
            : 'Agent connect'}</Dialog.Title
      >
      <Dialog.Description
        >{settings
          ? 'Manage project details, access, and lifecycle.'
          : utility === 'information'
            ? 'Project description and access.'
            : 'Connect an external agent to work in this project.'}</Dialog.Description
      >
    </Dialog.Header>
    <div class="min-h-0 overflow-y-auto px-1">
      {#if utility === 'information'}
        <ProjectOverview
          name={project.name}
          description={project.description}
          visibility={project.visibility}
          role={project.current_user_role}
        />
      {:else if settings}
        {#if project.current_user_role === 'OWNER'}
          {#await import('../sections/Settings.svelte')}<LoadingState
              >Opening settings…</LoadingState
            >{:then module}<module.default {project} embedded />{/await}
        {:else}<p>Only project owners can manage settings and membership.</p>{/if}
      {:else if utility === 'agent-connect'}
        {#await import('../sections/ProjectAgentConnect.svelte')}<LoadingState
            >Loading connection guide…</LoadingState
          >{:then module}<module.default
            projectId={project.id}
            projectName={project.name}
            signedIn={true}
            canWrite={canWriteProject(project.current_user_role, Boolean(project.archived_at))}
            embedded
          />{/await}
      {/if}
    </div>
  </Dialog.Content>
</Dialog.Root>
