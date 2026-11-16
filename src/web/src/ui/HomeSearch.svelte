<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { Search, ArrowRight, Sparkles, FolderOpen, Library } from '@lucide/svelte';
  import { projectContext } from '../svelte-lib/context';
  import { createLibraryApi } from '../lib/library-api';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';

  let { onAsk }: { onAsk: (question: string) => void } = $props();
  const { api, auth } = projectContext();
  const library = createLibraryApi({
    getAccessToken: auth.token,
    onUnauthorized: () => auth.expireSession(),
  });
  let shortcut = $state('Ctrl');
  onMount(() => {
    if (/Mac|iPhone|iPad/.test(navigator.platform)) shortcut = '⌘';
  });
  let value = $state('');
  let query = $state('');
  let open = $state(false);
  let form = $state<HTMLFormElement>();
  let input = $state<HTMLInputElement | null>(null);
  const term = $derived(value.trim());
  $effect(() => {
    const next = term;
    const timer = setTimeout(() => {
      query = next;
    }, 200);
    return () => clearTimeout(timer);
  });
  const projects = createQuery(
    toStore(() => ({
      queryKey: ['home-search-projects', auth.signedIn, query],
      enabled: Boolean(query),
      queryFn: () =>
        auth.signedIn
          ? api.listProjects(undefined, query, 'active', 'relevance')
          : api.listPublicProjects(query, undefined, 'relevance'),
    })),
  );
  const items = createQuery(
    toStore(() => ({
      queryKey: ['home-search-library', query],
      enabled: Boolean(query),
      queryFn: () => library.list({ q: query }),
    })),
  );
  export function focus() {
    input?.focus();
    open = true;
  }
  async function keyboard(event: KeyboardEvent) {
    if (!(event.target instanceof Node) || !form?.contains(event.target)) return;
    if (event.key === 'Escape') {
      input?.focus();
      open = false;
      event.preventDefault();
    }
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    event.preventDefault();
    open = true;
    await tick();
    const choices = Array.from(
      form?.querySelectorAll<HTMLElement>('.search-results a, .search-results button') ?? [],
    );
    const index = choices.indexOf(document.activeElement as HTMLElement);
    const next = index + (event.key === 'ArrowDown' ? 1 : -1);
    if (next < 0) input?.focus();
    else choices[Math.min(next, choices.length - 1)]?.focus();
  }
</script>

<svelte:window onkeydown={keyboard} />

<form
  bind:this={form}
  class="search-container"
  role="search"
  aria-label="Search Polycolab"
  onfocusout={(event) => {
    if (!(event.relatedTarget instanceof Node) || !form?.contains(event.relatedTarget))
      open = false;
  }}
  onsubmit={(event) => {
    event.preventDefault();
    query = term;
    open = true;
    input?.focus();
  }}
>
  <div class="search-bar">
    <Search size={18} aria-hidden="true" />
    <Input
      aria-label="Search"
      placeholder="Search"
      maxlength={200}
      bind:value
      bind:ref={input}
      oninput={() => {
        open = true;
      }}
      onfocus={() => {
        open = true;
      }}
      aria-expanded={open}
      aria-controls="home-search-suggestions"
      aria-describedby="home-search-help"
    />
    <span class="search-shortcut" aria-hidden="true"><kbd>{shortcut}</kbd><kbd>K</kbd></span>
    <Button type="submit" variant="ghost" size="icon-sm" aria-label="Search" title="Search"
      ><ArrowRight size={18} aria-hidden="true" /></Button
    >
  </div>
  <span id="home-search-help" class="sr-only"
    >Search projects and Library items, or ask the research assistant. Use the down arrow to explore
    suggestions.</span
  >
  {#if open}
    <section id="home-search-suggestions" class="search-results" aria-label="Search suggestions">
      <div class="results-scroll">
        {#if term}
          <button
            class="result"
            type="button"
            onclick={() => {
              open = false;
              onAsk(term);
            }}
          >
            <Sparkles size={16} aria-hidden="true" />
            <span class="result-label">Ask AI</span><span class="result-context">— “{term}”</span>
            <ArrowRight class="result-arrow" size={16} aria-hidden="true" />
          </button>
          {#if query !== term || $projects.isPending || $projects.isError || $projects.data?.items.length}
            <div class="result-group">
              <h2>Projects</h2>
              {#if query !== term || $projects.isPending}<p role="status">Searching projects…</p>
              {:else if $projects.isError}<p role="alert">
                  Could not search projects. <button
                    type="button"
                    onclick={() => $projects.refetch()}>Retry</button
                  >
                </p>
              {:else}{#each ($projects.data?.items ?? []).slice(0, 4) as project (project.id)}
                  <a class="result" href={`/projects/${project.id}`} aria-label={project.name}>
                    <FolderOpen size={16} aria-hidden="true" /><span class="result-label"
                      >{project.name}</span
                    >
                    <span class="result-context" aria-hidden="true">— Projects</span>
                    <ArrowRight class="result-arrow" size={16} aria-hidden="true" />
                  </a>
                {/each}{/if}
            </div>
          {/if}
          {#if query !== term || $items.isPending || $items.isError || $items.data?.items.length}
            <div class="result-group">
              <h2>Library</h2>
              {#if query !== term || $items.isPending}<p role="status">Searching Library…</p>
              {:else if $items.isError}<p role="alert">
                  Could not search Library. <button type="button" onclick={() => $items.refetch()}
                    >Retry</button
                  >
                </p>
              {:else}{#each ($items.data?.items ?? []).slice(0, 4) as item (item.id)}
                  <a
                    class="result"
                    href={`/library/items/${item.id}`}
                    aria-label={item.version.content.title}
                  >
                    <Library size={16} aria-hidden="true" /><span class="result-label"
                      >{item.version.content.title}</span
                    >
                    <span class="result-context" aria-hidden="true">— Library</span>
                    <ArrowRight class="result-arrow" size={16} aria-hidden="true" />
                  </a>
                {/each}{/if}
            </div>
          {/if}
        {:else}
          <h2>Search tips</h2>
          <div class="search-tip">
            <FolderOpen size={16} aria-hidden="true" /><span
              >Projects <span class="tip-context">— Find research projects</span></span
            >
          </div>
          <div class="search-tip">
            <Library size={16} aria-hidden="true" /><span
              >Library <span class="tip-context">— Find prompts, skills, and plugins</span></span
            >
          </div>
          <div class="search-tip">
            <Sparkles size={16} aria-hidden="true" /><span>Ask AI</span>
          </div>
        {/if}
      </div>
      <div class="search-footer" aria-hidden="true">
        <span><kbd>↑</kbd><kbd>↓</kbd> to navigate</span>
        <span><kbd>↵</kbd> to select</span>
      </div>
    </section>
  {/if}
</form>

<style>
  .search-container {
    position: relative;
  }
  .search-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 7px 5px 16px;
    background: var(--background);
    border: 1px solid var(--input);
    border-radius: 12px;
    box-shadow:
      0 0 0 5px var(--muted),
      0 2px 4px var(--polycolab-shadow);
    color: var(--muted-foreground);
  }
  .search-bar:focus-within {
    outline: 2px solid var(--ring);
    outline-offset: 4px;
  }
  .search-bar :global(input) {
    flex: 1;
    min-width: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    height: 38px;
    padding-left: 0;
  }
  .search-bar :global(input:focus-visible) {
    box-shadow: none;
    outline: none;
  }
  .search-shortcut {
    display: flex;
    gap: 4px;
  }
  kbd {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 4px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-family: inherit;
    font-size: 11px;
    line-height: 1;
  }
  .search-results {
    position: absolute;
    top: calc(100% + 8px);
    left: 0;
    right: 0;
    z-index: 20;
    display: flex;
    flex-direction: column;
    max-height: min(520px, 60dvh);
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--popover);
    box-shadow: var(--shadow-raised);
  }
  .results-scroll {
    min-height: 0;
    overflow-y: auto;
    padding: 8px;
  }
  .result-group {
    padding-top: 8px;
  }
  h2 {
    font-size: 12px;
    font-weight: 500;
    margin: 0;
    padding: 6px 8px;
    color: var(--muted-foreground);
  }
  p {
    font-size: 12px;
    color: var(--muted-foreground);
    padding: 8px;
    margin: 0;
  }
  p button {
    text-decoration: underline;
    cursor: pointer;
  }
  .result,
  .search-tip {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 36px;
    padding: 8px;
    font-size: 13px;
    line-height: 20px;
    text-align: left;
  }
  .result {
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--foreground);
    cursor: pointer;
  }
  .result :global(svg),
  .search-tip :global(svg) {
    flex-shrink: 0;
    color: var(--muted-foreground);
  }
  .result-label,
  .result-context {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .result-context,
  .tip-context {
    color: var(--muted-foreground);
  }
  .result-context {
    flex: 1;
  }
  .result :global(.result-arrow) {
    margin-left: auto;
    opacity: 0;
  }
  .result:hover,
  .result:focus-visible {
    background: var(--muted);
  }
  .result:hover :global(.result-arrow),
  .result:focus-visible :global(.result-arrow) {
    opacity: 1;
  }
  .search-footer {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    padding: 10px 16px;
    background: var(--muted);
    color: var(--muted-foreground);
    font-size: 11px;
  }
  .search-footer > span {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  a:focus-visible,
  button:focus-visible {
    outline: 1px solid var(--ring);
    outline-offset: -1px;
  }
  @media (max-width: 480px) {
    .search-shortcut {
      display: none;
    }
  }
</style>
