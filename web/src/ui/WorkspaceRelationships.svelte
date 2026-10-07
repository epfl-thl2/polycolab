<script lang="ts">
  import { relationshipEndpoints } from '../lib/relationship-view';
  import { groupRelationships } from '../lib/relationship-groups';
  import type { WorkspaceMap } from '../lib/workspace-map';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import { Button } from '../lib/components/ui/button';
  let {
    projectId,
    data,
    objectId,
    revisionId,
  }: { projectId: string; data?: WorkspaceMap; objectId: string; revisionId?: string } = $props();
  let relationCount = $state(100);
  const filtered = $derived(
    data && revisionId
      ? {
          ...data,
          relations: data.relations.filter(
            (relation) =>
              relationshipEndpoints(relation)[0] === revisionId ||
              relationshipEndpoints(relation)[1] === revisionId,
          ),
        }
      : data,
  );
  const groups = $derived(groupRelationships(filtered, objectId));
  const hasMore = $derived(groups.some((group) => group.items.length > relationCount));
  $effect(() => {
    void objectId;
    void revisionId;
    relationCount = 100;
  });
</script>

{#each groups as group (group.label)}
  <section class="relationship-group" aria-label={group.label}>
    <h4>{group.label} <span class="muted">({group.items.length})</span></h4>
    <ul class="relationship-list">
      {#each group.items.slice(0, relationCount) as item (item.relation.id)}
        {@const relatedNode = data?.nodes.find(
          (node) => node.object_version_id === item.otherRevisionId,
        )}
        {@const relatedObject = data?.objects.find(
          (object) => object.id === relatedNode?.object_id,
        )}
        <li class="panel-card">
          <div class="relationship-title">
            {@render endpoint(item.otherRevisionId)}
            {#if relatedObject}<ObjectKindBadge kind={relatedObject.kind} />{/if}
            {#if item.direction === 'incoming'}<span class="muted"
                >{item.display.label} → this object</span
              >{/if}
          </div>
          <details class="exact-relation">
            <summary>Connection versions</summary>
            {#each item.display.originals as original (original.id)}<dl>
                <div>
                  <dt>{original.direction === 'BIDIRECTIONAL' ? 'First endpoint' : 'Source'}</dt>
                  <dd>{@render endpoint(relationshipEndpoints(original)[0])}</dd>
                </div>
                <div>
                  <dt>
                    {original.direction === 'BIDIRECTIONAL' ? 'Second endpoint' : 'Target'}
                  </dt>
                  <dd>{@render endpoint(relationshipEndpoints(original)[1])}</dd>
                </div>
              </dl>{/each}
          </details>
        </li>
      {/each}
    </ul>
  </section>
{:else}<p class="muted">No relationships to show.</p>{/each}
{#if hasMore}<Button variant="outline" onclick={() => (relationCount += 100)}
    >Show next relationships</Button
  >{/if}
{#snippet endpoint(revisionId: string)}
  {@const node = data?.nodes.find((node) => node.object_version_id === revisionId)}
  {@const current = data?.objects.find(
    (object) => object.current_object_version.id === revisionId,
  )?.current_object_version}
  {@const number = node?.object_version_number ?? current?.number}
  {#if node}<a class="endpoint" href={`/workspaces/${projectId}/records/${revisionId}`}>
      <span>{node.title}</span>
      {#if number !== undefined}<span class="version">v{number}</span>{/if}
    </a>
  {:else}<span class="muted">External object · version unavailable</span>{/if}
{/snippet}

<style>
  .relationship-group h4 {
    font-size: 13px;
    font-weight: 400;
    margin: 10px 0 4px;
  }
  .exact-relation {
    margin: 0;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .exact-relation summary {
    margin: 0;
    cursor: pointer;
    font-weight: 400;
  }
  .exact-relation dl {
    display: grid;
    gap: 4px;
    margin: 4px 0 0;
  }
  .exact-relation dt {
    margin-bottom: 2px;
  }
  .exact-relation dd {
    margin: 0;
  }
  .endpoint {
    display: flex;
    align-items: baseline;
    gap: 5px;
    min-width: 0;
    font-size: 13px;
    color: var(--foreground);
    text-decoration: none;
    line-height: 1.35;
  }
  .relationship-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
  }
  .relationship-title .endpoint {
    flex: 1;
  }
  .relationship-title .endpoint > span:first-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .endpoint:hover {
    text-decoration: underline;
  }
  .version {
    flex-shrink: 0;
    color: var(--muted-foreground);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .panel-card {
    display: grid;
    gap: 3px;
    padding: 6px 8px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .relationship-list {
    display: grid;
    gap: 4px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .relationship-list li {
    overflow-wrap: anywhere;
  }
  .relationship-list :global(button) {
    white-space: normal;
    height: auto;
    text-align: left;
    justify-content: start;
  }
</style>
