<script lang="ts">
  import { relationshipChoices, type DisplayRelationshipKind } from '../lib/display-relationships';

  import { objectProgress } from '../lib/object-progress';
  import { reviewSummaries } from '../lib/reviews-api';
  import { relationshipEndpoints } from '../lib/relationship-view';
  import { Search, Maximize, LocateFixed, UserRound, Sparkles } from '@lucide/svelte';
  import WorkspaceMapViewport from './WorkspaceMapViewport.svelte';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { SvelteSet } from 'svelte/reactivity';
  import { untrack } from 'svelte';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    SvelteFlow,
    Background,
    Controls,
    MarkerType,
    type Node,
    type Edge,
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { workspace, explain } from '../svelte-lib/context';
  import { loadWorkspaceMap, objectDiagram, type WorkspaceMap } from '../lib/workspace-map';
  import WorkspaceMapBrowser from './WorkspaceMapBrowser.svelte';
  import WorkspaceMapNode from './WorkspaceMapNode.svelte';
  import WorkspaceMapEdge from './WorkspaceMapEdge.svelte';
  import MapNodeShape from './MapNodeShape.svelte';
  import { objectKindVisual, objectKinds } from '../lib/object-kind-visual';
  const edgeTypes = { relationship: WorkspaceMapEdge };
  const nodeTypes = { object: WorkspaceMapNode };
  import DenseGraph from './DenseGraph.svelte';
  let {
    projectId,
    publicRead = false,
    objectId = $bindable(''),
    initialFocusId,
    ondata = () => {},
    onreview = () => {},
    onfocus = () => {},
  }: {
    projectId: string;
    publicRead?: boolean;
    objectId?: string;
    initialFocusId?: string;
    ondata?: (data: WorkspaceMap | undefined) => void;
    onreview?: (objectId: string) => void;
    onfocus?: (objectId: string) => void;
  } = $props();
  let graphWidth = $state(0);
  let graphHeight = $state(0);
  let mapActions = $state<{ fitAll: () => void; centerFocused: () => void }>();
  let hoveredEdgeId = $state<string>();
  let objectBrowser = $state<{ focusSearch: () => void }>();
  const { api, query } = workspace();
  const graph = createQuery(
    toStore(() => ({
      queryKey: ['workspace-map', projectId, publicRead, 'layout'],
      queryFn: async () => {
        const data = await query.fetchQuery({
          queryKey: ['workspace-map', projectId, publicRead, 'data'],
          queryFn: () => loadWorkspaceMap(api, projectId, publicRead),
          staleTime: 30_000,
        });
        const { layoutMap } = await import('../lib/workspace-map-layout-browser');
        const diagram = objectDiagram(data);
        return { ...data, diagram, layout: await layoutMap(diagram) };
      },
    })),
  );
  const summaries = createQuery(
    toStore(() => ({
      queryKey: [
        'review-summaries',
        projectId,
        publicRead,
        $graph.data?.objects.map((object) => object.current_object_version.id),
      ],
      enabled: Boolean($graph.data),
      queryFn: async () => {
        const ids = ($graph.data?.objects ?? []).map((object) => object.current_object_version.id);
        const items = [];
        for (let offset = 0; offset < ids.length; offset += 128)
          items.push(
            ...(await reviewSummaries(
              ids.slice(offset, offset + 128),
              publicRead ? undefined : projectId,
            )),
          );
        return items;
      },
    })),
  );
  const focused = $derived($graph.data?.objects.find((object) => object.id === objectId));
  const hasDirectedRelations = $derived(
    $graph.data?.diagram.relations.some((relation) => relation.direction !== 'BIDIRECTIONAL') ??
      false,
  );
  $effect(() => {
    const data = $graph.data;
    // Parent panel state must not become a dependency of this data notification.
    untrack(() => ondata(data));
  });
  const linked = $derived.by(() => {
    const ids = new SvelteSet(
      ($graph.data?.diagram.nodes ?? [])
        .filter((node) => node.object_id === objectId)
        .map((node) => node.object_version_id),
    );
    const neighbors = new SvelteSet(ids);
    for (const link of $graph.data?.diagram.relations ?? []) {
      if (ids.has(relationshipEndpoints(link)[0]) || ids.has(relationshipEndpoints(link)[1])) {
        neighbors.add(relationshipEndpoints(link)[0]);
        neighbors.add(relationshipEndpoints(link)[1]);
      }
    }
    return neighbors;
  });
  const nodes = $derived<Node[]>(
    ($graph.data?.diagram.nodes ?? []).map((node) => ({
      id: node.object_version_id,
      type: 'object',
      initialWidth: $graph.data!.layout.sizes[node.object_version_id].width,
      initialHeight: $graph.data!.layout.sizes[node.object_version_id].height,
      position: $graph.data!.layout.positions[node.object_version_id],
      data: {
        label: node.title,
        progress: objectProgress(
          $graph.data?.objects.find(
            (object) => object.current_object_version.id === node.object_version_id,
          )?.current_object_version,
        ),
        review: $summaries.data?.find((item) => item.object_version_id === node.object_version_id),
        onreview: () => {
          focus(node.object_id);
          onreview(node.object_id);
        },
        size: $graph.data!.layout.sizes[node.object_version_id],
        kind: $graph.data?.objects.find((object) => object.id === node.object_id)?.kind,
        revisionLabel: $graph.data?.objects.find(
          (object) => object.current_object_version.id === node.object_version_id,
        )
          ? `Version ${$graph.data?.objects.find((object) => object.current_object_version.id === node.object_version_id)?.current_object_version.number}`
          : 'Linked historical version',
      },
      selected: node.object_id === objectId,
      style: `opacity:${focused && !linked.has(node.object_version_id) ? 0.45 : 1}`,
    })),
  );
  const nodeIds = $derived(new SvelteSet(nodes.map((node) => node.id)));
  const focusedNodeIds = $derived(
    new SvelteSet(nodes.filter((node) => node.selected).map((node) => node.id)),
  );
  const edges = $derived<Edge[]>(
    ($graph.data?.diagram.relations ?? [])
      .filter(
        (relation) =>
          nodeIds.has(relationshipEndpoints(relation)[0]) &&
          nodeIds.has(relationshipEndpoints(relation)[1]),
      )
      .map((relation) => {
        const connected = Boolean(
          focused && relationshipEndpoints(relation).some((id) => focusedNodeIds.has(id)),
        );
        const color = connected
          ? 'var(--brand)'
          : 'color-mix(in srgb, var(--muted-foreground) 55%, var(--panel))';
        return {
          id: relation.id,
          type: 'relationship',
          markerEnd:
            relation.direction === 'BIDIRECTIONAL'
              ? undefined
              : {
                  type: MarkerType.ArrowClosed,
                  width: 22,
                  height: 22,
                  color,
                },
          style: `stroke:${color};stroke-width:${connected ? 1.5 : 1};opacity:${focused && !connected ? 0.25 : 1};`,
          data: {
            route: $graph.data!.layout.routes[relation.id],
            showLabel: connected || hoveredEdgeId === relation.id,
          },
          source: relationshipEndpoints(relation)[0],
          target: relationshipEndpoints(relation)[1],
          label: relationshipChoices[relation.relationship_type as DisplayRelationshipKind],
          selected: connected,
        };
      }),
  );

  function focus(id: string) {
    objectId = id;
    onfocus(id);
  }
</script>

<h1 class="sr-only">Map</h1>
{#if $graph.isPending}<LoadingState>Loading workspace map…</LoadingState>
{:else if $graph.isError}<Alert.Root variant="destructive" role="alert"
    >{explain($graph.error)}</Alert.Root
  ><Button onclick={() => $graph.refetch()}>Retry map</Button>
{:else if !$graph.data?.objects.length}<p>This workspace has no research objects yet.</p>
{:else}
  {#if $summaries.isError}<p class="muted" role="status">
      Review signals unavailable. <button onclick={() => $summaries.refetch()}>Retry</button>
    </p>{/if}
  <div class="map-actions">
    <Button variant="outline" onclick={() => mapActions?.fitAll()}
      ><Maximize size={16} aria-hidden="true" />Fit all</Button
    >
    <Button variant="outline" disabled={!focused} onclick={() => mapActions?.centerFocused()}
      ><LocateFixed size={16} aria-hidden="true" />Center focused object</Button
    >
    <Button variant="ghost" onclick={() => objectBrowser?.focusSearch()}
      ><Search size={16} aria-hidden="true" />Find object</Button
    >
  </div>
  <div class="graph" bind:clientWidth={graphWidth} bind:clientHeight={graphHeight}>
    {#if nodes.length > 50}<DenseGraph
        summaries={$summaries.data ?? []}
        nodes={$graph.data?.diagram.nodes ?? []}
        relations={($graph.data?.diagram.relations ?? []).filter((relation) =>
          relationshipEndpoints(relation).every((id) => nodeIds.has(id)),
        )}
        layout={$graph.data!.layout}
        focusedIds={focused ? [...linked] : []}
        focusedRevisionId={focused?.current_object_version.id}
        initialFocusId={$graph.data?.objects.find((object) => object.id === initialFocusId)
          ?.current_object_version.id}
        onready={(actions) => (mapActions = actions)}
      />
    {:else}<SvelteFlow
        proOptions={{ hideAttribution: true }}
        {nodes}
        {edges}
        {nodeTypes}
        {edgeTypes}
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        elevateEdgesOnSelect={false}
        nodesDraggable={false}
        nodesConnectable={false}
        autoPanOnNodeFocus={false}
        onlyRenderVisibleElements
        onedgepointerenter={({ edge }) => (hoveredEdgeId = edge.id)}
        onedgepointerleave={() => (hoveredEdgeId = undefined)}
        onnodeclick={({ node }) =>
          focus(
            $graph.data?.nodes.find((item) => item.object_version_id === node.id)?.object_id ?? '',
          )}
        ><Background gap={24} size={1} patternColor="var(--border)" /><Controls
          showFitView={false}
        /><WorkspaceMapViewport
          layout={$graph.data!.layout}
          focusedIds={focused ? [...linked] : []}
          focusedRevisionId={focused?.current_object_version.id}
          initialFocusId={$graph.data?.objects.find((object) => object.id === initialFocusId)
            ?.current_object_version.id}
          width={graphWidth}
          height={graphHeight}
          nodeSignature={nodes
            .map((node) => `${node.id}:${node.position.x}:${node.position.y}`)
            .join(',')}
          onready={(actions) => (mapActions = actions)}
        /></SvelteFlow
      >{/if}
  </div>
  <section class="map-legend" aria-label="Map legend">
    <h2>Legend</h2>
    <div class="map-legend-group">
      <span class="map-legend-label">Objects</span>
      {#each objectKinds.filter((kind) => !['NOTE', 'ATTEMPT', 'FORMALIZATION'].includes(kind)) as kind (kind)}<span
          class="map-legend-kind"
          ><span class="map-legend-swatch"><MapNodeShape {kind} /></span>{objectKindVisual(kind)
            .label}</span
        >{/each}
      <span class="map-legend-item"
        ><span class="map-legend-swatch"><MapNodeShape kind="PROOF" selected /></span>Focused object</span
      >
    </div>
    <div class="map-legend-group">
      <span class="map-legend-label">Reported progress</span>
      {#each [['In progress', '--status-progress'], ['Partial / stalled', '--status-attention'], ['Complete', '--status-complete'], ['Failed', '--status-issues']] as [label, color] (label)}
        <span class="map-legend-item"
          ><span class="progress-dot" style={`background:var(${color})`}></span>{label}</span
        >
      {/each}
    </div>
    <div class="map-legend-group">
      <span class="map-legend-label">Reviews</span>
      <span class="map-legend-item"><UserRound size={14} />Human reviewed</span>
      <span class="map-legend-item"><Sparkles size={14} />AI reviewed</span>
    </div>
    {#if hasDirectedRelations}<div class="map-legend-group">
        <span class="map-legend-label">Relationships</span>
        {#if hasDirectedRelations}<span class="map-legend-item"
            ><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2v14m-4-4 4 4 4-4" /></svg
            >Object → supporting object</span
          >{/if}

        <span class="map-legend-item">Line label names the relationship</span>
      </div>{/if}
  </section>
  <WorkspaceMapBrowser
    summaries={$summaries.data ?? []}
    {onreview}
    bind:this={objectBrowser}
    data={$graph.data!.diagram}
    bind:objectId
    onfocus={focus}
  />
{/if}

<style>
  .progress-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
  }
  .map-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
  }
  .graph {
    height: clamp(320px, 72vh, 760px);
    min-height: 320px;
  }
  .map-legend {
    display: grid;
    gap: 8px;
    margin-top: 12px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
  }
  .map-legend h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
  }
  .map-legend-group {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
  }
  .map-legend-label {
    min-width: 84px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .map-legend-kind {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--foreground);
    font-size: 12px;
  }
  .map-legend-swatch {
    position: relative;
    display: inline-block;
    flex: 0 0 auto;
    width: 28px;
    height: 18px;
  }
  .map-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .map-legend-item svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
</style>
