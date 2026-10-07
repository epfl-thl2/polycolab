<script lang="ts">
  import {
    reviewCount as countReviews,
    reviewLabel as describeReviews,
  } from '../lib/review-display';
  import ReviewSignals from './ReviewSignals.svelte';
  import { canonicalObjectKind } from '../lib/object-kind';
  import type { ReviewSummary } from '../lib/reviews-api';
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  import MapNodeShape from './MapNodeShape.svelte';
  import { objectKindVisual } from '../lib/object-kind-visual';
  import type { MapNodeSize } from '../lib/workspace-map-layout';
  let { data, selected }: NodeProps = $props();
  const review = $derived(data.review as ReviewSummary | undefined);
  const reviewCount = $derived(review ? countReviews(review.human) + countReviews(review.ai) : 0);
  const reviewLabel = $derived(review ? describeReviews(review) : '');
  const progress = $derived(data.progress as { label: string; color: string } | undefined);
  const size = $derived(data.size as MapNodeSize);
  const kind = $derived(canonicalObjectKind(String(data.kind ?? 'STATEMENT')));
</script>

<div
  class="object-node"
  class:proof={kind === 'PROOF'}
  title={String(data.label)}
  role="group"
  aria-label={`${objectKindVisual(kind).label}: ${String(data.label)}`}
  style={`width:${size.width}px;height:${size.height}px`}
>
  <MapNodeShape {kind} {selected} />
  {#if reviewCount}<button
      class="review-indicator nodrag nopan"
      title={reviewLabel}
      aria-label={`Open reviews. ${reviewLabel}`}
      onclick={(event) => {
        event.stopPropagation();
        (data.onreview as (() => void) | undefined)?.();
      }}
    >
      {#if review}<ReviewSignals {review} />{/if}
    </button>{/if}
  {#if progress}<span
      class="progress-dot"
      role="img"
      aria-label={`Reported progress: ${progress.label}`}
      title={`Reported progress: ${progress.label}. Not a verification result.`}
      style={`background:var(${progress.color})`}
    ></span>{/if}
  <Handle type="target" position={Position.Top} />
  <span class="object-title">{data.label}</span>
  <Handle type="source" position={Position.Bottom} />
</div>

<style>
  .progress-dot {
    position: absolute;
    left: 99%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 8px;
    height: 8px;
    border-radius: 50%;
    outline: 2px solid var(--panel);
    z-index: 2;
  }
  .review-indicator {
    position: absolute;
    right: -8px;
    top: -18px;
    z-index: 2;
    display: grid;
    place-items: center;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .review-indicator:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .object-node {
    position: relative;
    padding: 8px 20px;
    display: grid;
    align-items: center;
    justify-items: center;
    color: var(--foreground);
    text-align: center;
  }
  .object-node.proof {
    padding: 22px 30px;
  }
  .object-node.proof .object-title {
    font-size: 12px;
    line-height: 16px;
  }
  .object-title {
    position: relative;
    width: 100%;
    font-size: 13px;
    font-weight: 500;
    line-height: 1.4;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
  }
  .object-node :global(.svelte-flow__handle) {
    opacity: 0;
    width: 6px;
    height: 6px;
    background: var(--muted-foreground);
    border-color: var(--panel);
  }
</style>
