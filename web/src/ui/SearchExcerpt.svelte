<script lang="ts">
  import Markdown from './Markdown.svelte';
  let { content, query }: { content: string; query: string } = $props();
</script>

<div class="search-excerpt"><Markdown {content} searchQuery={query} /></div>

<style>
  .search-excerpt {
    max-height: 9rem;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
  .search-excerpt :global(.katex-display) {
    overflow-x: auto;
  }
</style>
