<script lang="ts">
  import { localMapViewport } from '../lib/workspace-map-viewport';
  import type { MapLayout } from '../lib/workspace-map-layout';
  import { useSvelteFlow } from '@xyflow/svelte';
  let {
    focusedRevisionId,
    initialFocusId,
    focusedIds = [],
    layout,
    width,
    height,
    nodeSignature,
    onready,
  }: {
    focusedRevisionId?: string;
    initialFocusId?: string;
    focusedIds?: string[];
    layout: MapLayout;
    width: number;
    height: number;
    nodeSignature: string;
    onready: (actions: { fitAll: () => void; centerFocused: () => void }) => void;
  } = $props();
  const flow = useSvelteFlow();
  const duration = () => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 220);
  let movement: Promise<unknown> = Promise.resolve();
  let latestRequest = 0;
  function move(action: () => Promise<unknown>) {
    const request = ++latestRequest;
    movement = movement
      .catch(() => undefined)
      .then(() => (request === latestRequest ? action() : undefined));
  }
  function fitAll() {
    move(() => flow.fitView({ padding: 0.2, maxZoom: 1, duration: duration() }));
  }
  function centerFocused() {
    const target = focusedRevisionId
      ? localMapViewport(layout, focusedRevisionId, focusedIds, width, height)
      : undefined;
    if (!target) return;
    move(() => flow.setCenter(target.x, target.y, { zoom: target.zoom, duration: duration() }));
  }

  $effect(() => {
    onready({ fitAll, centerFocused });
  });
  $effect(() => {
    void width;
    void height;
    void nodeSignature;
    const requestedFocus = initialFocusId;
    const frame = requestAnimationFrame(() => {
      if (requestedFocus && requestedFocus === focusedRevisionId) centerFocused();
      else fitAll();
    });
    return () => cancelAnimationFrame(frame);
  });
</script>
