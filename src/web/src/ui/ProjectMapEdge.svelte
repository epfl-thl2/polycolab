<script lang="ts">
  import { BaseEdge, type EdgeProps } from '@xyflow/svelte';
  import { roundedRoute, type MapLayout } from '../lib/project-map-layout';
  let { id, markerEnd, label, style, data, selected }: EdgeProps = $props();
  const route = $derived(data?.route as MapLayout['routes'][string] | undefined);
</script>

{#if route}<BaseEdge
    {id}
    path={roundedRoute(route.points)}
    {markerEnd}
    label={data?.showLabel || selected ? label : undefined}
    labelX={route.label.x}
    labelY={route.label.y}
    {style}
    labelStyle="font-size:11px;color:var(--muted-foreground);background:var(--panel);padding:2px 4px;border-radius:4px;"
  />
{/if}
