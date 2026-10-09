<script lang="ts">
  import { objectKindVisual } from '../lib/object-kind-visual';
  import { mapNodeShape } from '../lib/map-node-shape';
  let { kind, selected = false }: { kind: string; selected?: boolean } = $props();
  const shape = $derived(mapNodeShape(kind));
  const visual = $derived(objectKindVisual(kind));
  const path = $derived(
    shape === 'diamond'
      ? 'M50 1L99 50L50 99L1 50Z'
      : shape === 'square'
        ? 'M1 1H99V99H1Z'
        : shape === 'oval'
          ? 'M99 50a49 49 0 1 1-98 0a49 49 0 1 1 98 0'
          : shape === 'hexagon'
            ? 'M10 1H90L99 50L90 99H10L1 50Z'
            : shape === 'trapezoid'
              ? 'M10 1H90L99 99H1Z'
              : shape === 'cut-corner'
                ? 'M1 1H84L99 16V99H1Z'
                : 'M13 1H87A12 12 0 0 1 99 13V87A12 12 0 0 1 87 99H13A12 12 0 0 1 1 87V13A12 12 0 0 1 13 1Z',
  );
</script>

<svg
  class="map-node-shape"
  class:selected
  data-map-shape={shape}
  viewBox="0 0 100 100"
  preserveAspectRatio="none"
  style={`--map-kind-color:var(${visual.color})`}
  aria-hidden="true"
>
  {#if selected}
    <path class="focus-ring" d={path} />
    <path class="focus-gap" d={path} />
  {/if}
  <path class="kind-shape" d={path} />
</svg>

<style>
  .map-node-shape {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: visible;
    pointer-events: none;
  }
  .map-node-shape path {
    vector-effect: non-scaling-stroke;
  }
  .map-node-shape .kind-shape {
    fill: color-mix(in srgb, var(--map-kind-color) 5%, var(--panel));
    stroke: var(--map-kind-color);
    stroke-width: 1;
  }
  .map-node-shape .focus-ring,
  .map-node-shape .focus-gap {
    fill: none;
  }
  .map-node-shape .focus-ring {
    stroke: var(--brand);
    stroke-width: 10;
  }
  .map-node-shape .focus-gap {
    stroke: var(--panel);
    stroke-width: 5;
  }
</style>
