<script lang="ts">
  import { Background, Controls, SvelteFlow } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import type { ProofSketchView } from '../lib/assurance-view';
  import { proofGraph } from '../lib/proof-graph';

  let { alternatives }: { alternatives: ProofSketchView[] } = $props();
  const graph = $derived(proofGraph(alternatives));
</script>

{#if alternatives.length > 0}
  <figure>
    <figcaption>
      Proof-sketch prerequisite graph. The alternative-sketch list contains the same structure in a
      keyboard-readable form.
    </figcaption>
    <div class="proof-graph" aria-hidden="true">
      <SvelteFlow
        nodes={graph.nodes}
        edges={graph.edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onlyRenderVisibleElements
      >
        <Background />
        <Controls />
      </SvelteFlow>
    </div>
  </figure>
{/if}

<style>
  figure {
    margin: 1.5rem 0;
  }

  figcaption {
    margin-bottom: 0.5rem;
    color: var(--demo-muted, #53615e);
  }

  .proof-graph {
    height: min(34rem, 65vh);
    min-height: 20rem;
    border: 1px solid var(--demo-line, #c9cecc);
    border-radius: 0.5rem;
    background: #fbfaf6;
  }
</style>
