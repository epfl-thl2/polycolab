<script lang="ts">
  import { highlightParts } from '../lib/search-excerpt';
  let { text, query }: { text: string; query: string } = $props();
</script>

{#each highlightParts(text, query) as part, index (index)}{#if part.match}<mark>{part.text}</mark
    >{:else}{part.text}{/if}{/each}
