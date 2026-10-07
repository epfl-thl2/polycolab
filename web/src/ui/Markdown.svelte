<script lang="ts">
  import { renderSearchExcerpt } from '../lib/search-excerpt';
  import { renderMarkdown } from '../svelte-lib/markdown';
  import 'katex/dist/katex.min.css';
  let { content, searchQuery }: { content: string; searchQuery?: string } = $props();
  const html = $derived(
    searchQuery === undefined ? renderMarkdown(content) : renderSearchExcerpt(content, searchQuery),
  );
</script>

<div class="prose">{@html html}</div>
