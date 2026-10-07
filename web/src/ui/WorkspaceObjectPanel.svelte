<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { workspace, explain } from '../svelte-lib/context';
  import { loadWorkspaceMap } from '../lib/workspace-map';
  import WorkspaceMapPanel from './WorkspaceMapPanel.svelte';
  import { Button } from '../lib/components/ui/button';
  let {
    projectId,
    objectId,
    publicRead,
    activeTab = $bindable('body'),
  }: { projectId: string; objectId: string; publicRead: boolean; activeTab?: string } = $props();
  const { api } = workspace();
  const object = createQuery(
    toStore(() => ({
      queryKey: ['object', projectId, objectId],
      queryFn: () => api.getObject(projectId, objectId, publicRead),
    })),
  );
  const map = createQuery(
    toStore(() => ({
      queryKey: ['workspace-inspector-map', projectId, publicRead],
      enabled: activeTab === 'relationships',
      queryFn: () => loadWorkspaceMap(api, projectId, publicRead),
    })),
  );
</script>

{#if $object.isPending}<p class="muted" role="status">Loading object…</p>
{:else if $object.isError}<p role="alert">{explain($object.error)}</p>
  <Button variant="outline" onclick={() => $object.refetch()}>Retry object</Button>
{:else}<WorkspaceMapPanel
    {projectId}
    {objectId}
    focusedObject={$object.data}
    data={$map.data}
    bind:activeTab
    clearable={false}
    pending={$map.isPending}
    error={$map.isError ? explain($map.error) : ''}
    onretry={() => $map.refetch()}
  />{/if}
