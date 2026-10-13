<script lang="ts">
  import { reviewCount } from '../lib/review-display';
  import type { ReviewSummary } from '../lib/reviews-api';
  import { localMapViewport } from '../lib/project-map-viewport';
  import { onMount, untrack } from 'svelte';
  import type { Relation } from '../lib/research-api';
  import type { MapLayout, Point } from '../lib/project-map-layout';

  type DenseNode = { object_version_id: string };
  type DenseRelation = Relation;
  let {
    summaries = [],
    nodes,
    relations,
    layout,
    focusedIds = [],
    focusedRevisionId,
    initialFocusId,
    onready = () => {},
  }: {
    summaries?: ReviewSummary[];
    layout: MapLayout;
    nodes: DenseNode[];
    relations: DenseRelation[];
    focusedIds?: string[];
    focusedRevisionId?: string;
    initialFocusId?: string;
    onready?: (actions: { fitAll: () => void; centerFocused: () => void }) => void;
  } = $props();
  let centeredNeighbors = $state<string[]>([]);
  let centeredRevision = $state<string | undefined>();
  $effect(() => {
    const id = initialFocusId;
    untrack(() => {
      centeredRevision = id;
      centeredNeighbors = id ? [...focusedIds] : [];
    });
  });
  $effect(() => {
    onready({
      fitAll: () => {
        centeredRevision = undefined;
      },
      centerFocused: () => {
        centeredRevision = focusedRevisionId;
        centeredNeighbors = [...focusedIds];
      },
    });
  });
  let canvas: HTMLCanvasElement;

  function draw(currentNodes = nodes, currentRelations = relations) {
    if (!canvas) return;
    const width = Math.max(1, Math.floor(canvas.getBoundingClientRect().width));
    const height = Math.max(280, Math.floor(canvas.getBoundingClientRect().height));
    const scale = Math.min(devicePixelRatio, 2);
    canvas.width = width * scale;
    canvas.height = height * scale;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.scale(scale, scale);
    context.clearRect(0, 0, width, height);

    const local = centeredRevision
      ? localMapViewport(layout, centeredRevision, centeredNeighbors, width, height)
      : undefined;
    const zoom =
      local?.zoom ??
      Math.min(
        (width - 36) / Math.max(1, layout.width),
        (height - 36) / Math.max(1, layout.height),
      );
    const offsetX = local ? width / 2 - local.x * zoom : (width - layout.width * zoom) / 2;
    const offsetY = local ? height / 2 - local.y * zoom : (height - layout.height * zoom) / 2;
    const project = (point: Point) => ({
      x: point.x * zoom + offsetX,
      y: point.y * zoom + offsetY,
    });
    const positions: Record<string, Point> = Object.create(null);
    for (const node of currentNodes) {
      const point = layout.positions[node.object_version_id];
      const size = layout.sizes[node.object_version_id];
      if (point && size)
        positions[node.object_version_id] = project({
          x: point.x + size.width / 2,
          y: point.y + size.height / 2,
        });
    }
    const theme = getComputedStyle(canvas);
    context.strokeStyle = theme.getPropertyValue('--border').trim() || '#c9cecc';
    context.lineWidth = 0.75;
    context.beginPath();
    for (const relation of currentRelations) {
      const points = layout.routes[relation.id]?.points.map(project);
      if (!points || points.length < 2) continue;
      context.moveTo(points[0].x, points[0].y);
      for (const point of points.slice(1)) context.lineTo(point.x, point.y);
      if (relation.direction === 'BIDIRECTIONAL') continue;
      const source = points[points.length - 2];
      const target = points[points.length - 1];
      const angle = Math.atan2(target.y - source.y, target.x - source.x);
      const tipX = target.x;
      const tipY = target.y;
      context.moveTo(tipX - Math.cos(angle - 0.5) * 6, tipY - Math.sin(angle - 0.5) * 6);
      context.lineTo(tipX, tipY);
      context.lineTo(tipX - Math.cos(angle + 0.5) * 6, tipY - Math.sin(angle + 0.5) * 6);
    }
    context.stroke();

    for (const [id, position] of Object.entries(positions)) {
      context.fillStyle = theme.getPropertyValue('--object-definition').trim() || '#64748b';
      context.globalAlpha = focusedIds.length && !focusedIds.includes(id) ? 0.2 : 1;
      context.beginPath();
      context.moveTo(position.x + 2.25, position.y);
      context.arc(position.x, position.y, 2.25, 0, Math.PI * 2);
      context.fill();
      const review = summaries.find((item) => item.object_version_id === id);
      if (review && reviewCount(review.human) + reviewCount(review.ai)) {
        context.strokeStyle = theme.getPropertyValue('--foreground').trim() || '#222';
        context.beginPath();
        context.arc(position.x, position.y, 4.5, 0, Math.PI * 2);
        context.stroke();
      }
    }
  }

  onMount(() => {
    draw();
    const observer = new ResizeObserver(() => draw());
    observer.observe(canvas);
    return () => observer.disconnect();
  });

  $effect(() => {
    void focusedIds;
    void centeredRevision;
    void centeredNeighbors;
    draw(nodes, relations);
  });
</script>

<figure data-dense-graph>
  <canvas bind:this={canvas} aria-hidden="true"></canvas>
  <figcaption class="sr-only">
    Overview of {nodes.length} exact versions and {relations.length} relationships. Use the readable lists
    below for exact identities and navigation.
  </figcaption>
</figure>

<style>
  figure {
    margin: 0;
    height: 100%;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
  }
  figcaption {
    margin-top: 0.5rem;
  }
</style>
