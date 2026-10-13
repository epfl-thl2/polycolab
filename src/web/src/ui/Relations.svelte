<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import ProjectRelationships from './ProjectRelationships.svelte';
  import { loadProjectMap } from '../lib/project-map';
  import { createQuery, createInfiniteQuery } from '@tanstack/svelte-query';
  import { projectContext, explain } from '../svelte-lib/context';
  import {
    relationshipChoices,
    relationshipWrite,
    type DisplayRelationshipKind,
  } from '../lib/display-relationships';
  let {
    projectId,
    objectId,
    revisionId,
    canWrite,
  }: { projectId: string; objectId: string; revisionId: string; canWrite: boolean } = $props();
  const { api, query } = projectContext();
  let adding = $state(false);
  let target = $state('');
  let rationale = $state('');
  let type = $state<DisplayRelationshipKind>('DEPENDS_ON');
  let error = $state('');
  let busy = $state(false);
  const map = createQuery(
    toStore(() => ({
      queryKey: ['project-inspector-map', projectId, false],
      queryFn: () => loadProjectMap(api, projectId, false),
    })),
  );
  const objects = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['objects', projectId],
      enabled: adding,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listObjects(projectId, false, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  async function add(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      const common = {
        destination: { kind: 'project' as const, project_id: projectId },
        description: rationale || null,
      };
      await api.createRelation(objectId, {
        ...common,
        ...relationshipWrite(type, revisionId, target),
      });
      adding = false;
      target = '';
      rationale = '';
      await query.invalidateQueries({ queryKey: ['relations'] });
      await query.invalidateQueries({ queryKey: ['neighborhood'] });
      await query.invalidateQueries({ queryKey: ['project-inspector-map', projectId] });
      await query.invalidateQueries({
        queryKey: ['project-map', projectId],
        refetchType: 'none',
      });
      await query.invalidateQueries({ queryKey: ['project-map', projectId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<div class="heading">
  <h2>Relationships</h2>
  <a href={`/projects/${projectId}/map?object=${objectId}&revision=${revisionId}`}>View on map →</a>
</div>
{#if $map.isError}<Alert.Root variant="destructive" role="alert">{explain($map.error)}</Alert.Root
  ><Button onclick={() => $map.refetch()}>Retry</Button>
{:else if $map.isPending}<LoadingState>Loading relationships…</LoadingState>
{:else}<ProjectRelationships
    {projectId}
    {objectId}
    {revisionId}
    data={$map.data}
  />{/if}{#if canWrite}<Button
    type="submit"
    variant="outline"
    class="mt-6"
    onclick={() => (adding = !adding)}>{adding ? 'Close' : 'Add relationship'}</Button
  >{/if}
{#if adding && canWrite}<form class="card mt-6" onsubmit={add}>
    <Field.Label
      >Type<NativeSelect bind:value={type}
        >{#each Object.entries(relationshipChoices) as [value, label] (value)}<option {value}
            >{label}</option
          >{/each}</NativeSelect
      ></Field.Label
    ><Field.Label
      >Target version<NativeSelect required bind:value={target}
        ><option value="">Choose an object and its current version</option
        >{#each $objects.data?.pages.flatMap((p) => p.items) ?? [] as object (object.id)}{#if object.id !== objectId}<option
              value={object.current_object_version_id}
              >{object.current_object_version.content.title} · v{object.current_object_version
                .number}</option
            >{/if}{/each}</NativeSelect
      ></Field.Label
    >{#if $objects.isError}<Alert.Root variant="destructive" role="alert">
        {explain($objects.error)}
      </Alert.Root>{/if}{#if $objects.hasNextPage}<Button
        variant="outline"
        type="button"
        class=""
        onclick={() => $objects.fetchNextPage()}>Load more targets</Button
      >{/if}<Field.Label>Rationale<Textarea required bind:value={rationale}></Textarea></Field.Label
    >{#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}<Button
      type="submit"
      disabled={busy || !target}>Save relationship</Button
    >
  </form>{/if}
