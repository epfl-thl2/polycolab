<script lang="ts">
  import {
    ArrowRight,
    BookOpen,
    ChevronRight,
    FolderOpen,
    Library,
    MessageSquare,
    Settings,
  } from '@lucide/svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { projectContext } from '../svelte-lib/context';
  import { createLibraryApi } from '../lib/library-api';
  import { Button } from '../lib/components/ui/button';
  import RelativeTime from './RelativeTime.svelte';
  import AgentConnectDialog from './AgentConnectDialog.svelte';
  import HomeSearch from './HomeSearch.svelte';
  import ResearchHelperDialog from './ResearchHelperDialog.svelte';

  const { api, auth } = projectContext();
  const library = createLibraryApi({
    getAccessToken: auth.token,
    onUnauthorized: () => auth.expireSession(),
  });
  const projects = createQuery(
    toStore(() => ({
      queryKey: ['home-projects', auth.signedIn],
      queryFn: () =>
        auth.signedIn
          ? api.listProjects(undefined, undefined, 'active', 'updated')
          : api.listPublicProjects(undefined, undefined, 'updated'),
    })),
  );
  const items = createQuery({ queryKey: ['home-library'], queryFn: () => library.list() });
  let assistantOpen = $state(false);
  let assistantQuestion = $state('');
  let searchBox = $state<HomeSearch>();
  let agentDialogOpen = $state(false);
  let agentDialogTrigger = $state<HTMLButtonElement | null>(null);
  function openAgentDialog(event: MouseEvent) {
    agentDialogTrigger = event.currentTarget as HTMLButtonElement;
    agentDialogOpen = true;
  }
  const projectsHref = $derived(auth.signedIn ? '/projects' : '/projects?scope=public');
  function focusSearch(event: KeyboardEvent) {
    if (agentDialogOpen || assistantOpen) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      searchBox?.focus();
    }
  }
</script>

<svelte:window onkeydown={focusSearch} />
<AgentConnectDialog
  bind:open={agentDialogOpen}
  signedIn={auth.signedIn}
  trigger={agentDialogTrigger}
/>

<main id="main" class="home-page" tabindex="-1">
  <header class="home-intro">
    <button type="button" class="agent-pill" aria-haspopup="dialog" onclick={openAgentDialog}>
      <span>Onboard your agent</span>
      <span class="agent-logos" aria-hidden="true">
        <img src="/brand/agents/codex.svg" alt="" title="Codex" width="20" height="20" />
        <img
          src="/brand/agents/claude-code.svg"
          alt=""
          title="Claude Code"
          width="20"
          height="20"
        />
        <img src="/brand/agents/opencode.svg" alt="" title="OpenCode" width="20" height="20" />
        <img src="/brand/agents/pi.svg" alt="" title="Pi" width="20" height="20" />
      </span>
    </button>
    <h1>What are you researching?</h1>
  </header>

  <HomeSearch
    bind:this={searchBox}
    onAsk={(question) => {
      assistantQuestion = question;
      assistantOpen = true;
    }}
  />
  <ResearchHelperDialog
    bind:open={assistantOpen}
    question={assistantQuestion}
    onClose={() => searchBox?.focus()}
  />

  <div class="home-columns">
    <section aria-labelledby="home-projects">
      <div class="section-heading">
        <h2 id="home-projects">
          <a href={projectsHref}
            >{auth.signedIn ? 'Your projects' : 'Public projects'}
            <ChevronRight size={14} aria-hidden="true" /></a
          >
        </h2>
      </div>
      {#if $projects.isPending}<p class="list-message" role="status">Loading projects…</p>
      {:else if $projects.isError}<div class="list-message" role="alert">
          <p>Could not load projects.</p>
          <Button variant="link" onclick={() => $projects.refetch()}>Try again</Button>
        </div>
      {:else if !$projects.data?.items.length}<div class="empty-list">
          <FolderOpen size={22} aria-hidden="true" />
          <p>
            {auth.signedIn
              ? 'Make space for your next idea.'
              : 'Projects will appear here as they are shared.'}
          </p>
          <a href={projectsHref}
            >{auth.signedIn ? 'Create your first project' : 'Browse projects'}
            <ArrowRight size={14} aria-hidden="true" /></a
          >
        </div>
      {:else}<ul>
          {#each $projects.data.items.slice(0, 4) as project (project.id)}<li>
              <a class="resource-link" href={`/projects/${project.id}`}
                ><FolderOpen size={17} aria-hidden="true" /><span class="resource-copy"
                  ><span class="resource-title">{project.name}</span><span class="resource-detail"
                    >Updated <RelativeTime value={project.updated_at} /></span
                  ></span
                ><ChevronRight size={14} aria-hidden="true" /></a
              >
            </li>{/each}
        </ul>{/if}
    </section>

    <section aria-labelledby="home-library">
      <div class="section-heading">
        <h2 id="home-library">
          <a href="/library">Library <ChevronRight size={14} aria-hidden="true" /></a>
        </h2>
      </div>
      {#if $items.isPending}<p class="list-message" role="status">Loading library…</p>
      {:else if $items.isError}<div class="list-message" role="alert">
          <p>Could not load library.</p>
          <Button variant="link" onclick={() => $items.refetch()}>Try again</Button>
        </div>
      {:else if !$items.data?.items.length}<div class="empty-list">
          <Library size={22} aria-hidden="true" />
          <p>A shared home for prompts, skills, and plugins.</p>
          <a href="/library">Explore the library <ArrowRight size={14} aria-hidden="true" /></a>
        </div>
      {:else}<ul>
          {#each $items.data.items.slice(0, 4) as item (item.id)}<li>
              <a class="resource-link" href={`/library/items/${item.id}`}
                ><Library size={17} aria-hidden="true" /><span class="resource-copy"
                  ><span class="resource-title">{item.version.content.title}</span><span
                    class="resource-detail"
                    >{item.kind === 'PROMPT'
                      ? 'Prompt'
                      : item.kind === 'SKILL'
                        ? 'Skill'
                        : 'Plugin'}</span
                  ></span
                ><ChevronRight size={14} aria-hidden="true" /></a
              >
            </li>{/each}
        </ul>{/if}
    </section>

    <section aria-labelledby="home-shortcuts">
      <div class="section-heading"><h2 id="home-shortcuts">Quick links</h2></div>
      <ul class="shortcut-list">
        {#if auth.signedIn}
          <li>
            <a class="resource-link" href="/settings/conversation-history"
              ><MessageSquare size={17} aria-hidden="true" /><span>Conversation history</span
              ><ChevronRight size={14} aria-hidden="true" /></a
            >
          </li>
          <li>
            <a class="resource-link" href="/library/mine"
              ><Library size={17} aria-hidden="true" /><span>My library</span><ChevronRight
                size={14}
                aria-hidden="true"
              /></a
            >
          </li>
          <li>
            <a class="resource-link" href="/settings/provider-connections"
              ><Settings size={17} aria-hidden="true" /><span>Provider connections</span
              ><ChevronRight size={14} aria-hidden="true" /></a
            >
          </li>
        {/if}
        <li>
          <a class="resource-link" href="/docs/getting-started/" data-sveltekit-reload
            ><BookOpen size={17} aria-hidden="true" /><span>Getting started</span><ChevronRight
              size={14}
              aria-hidden="true"
            /></a
          >
        </li>
        {#if !auth.signedIn}<li>
            <a class="resource-link" href="/docs/guides/projects/" data-sveltekit-reload
              ><FolderOpen size={17} aria-hidden="true" /><span>Projects and collaboration</span
              ><ChevronRight size={14} aria-hidden="true" /></a
            >
          </li>
          <li>
            <a class="resource-link" href="/docs/guides/agents/" data-sveltekit-reload
              ><MessageSquare size={17} aria-hidden="true" /><span>Working with agents</span
              ><ChevronRight size={14} aria-hidden="true" /></a
            >
          </li>{/if}
      </ul>
    </section>
  </div>
</main>

<style>
  .home-page {
    max-width: 1048px;
    margin: 0 auto;
    padding: 64px 24px 64px;
  }
  .home-intro {
    text-align: center;
    margin-bottom: 32px;
  }
  .agent-pill {
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--background);
    padding: 8px 13px;
    font-size: 12px;
    text-decoration: none;
    color: var(--foreground);
  }
  .agent-logos {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: 2px;
  }
  .agent-logos img {
    display: block;
    object-fit: contain;
    flex-shrink: 0;
  }
  h1 {
    margin: 27px 0 10px;
    font-size: clamp(26px, 3.5vw, 34px);
    font-weight: 600;
    line-height: 1.25;
    letter-spacing: -1px;
  }
  .home-columns {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 32px;
    margin: 32px 0 44px;
    min-height: 235px;
  }
  .section-heading {
    min-height: 30px;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 5px 10px;
    margin-bottom: 8px;
  }
  .section-heading h2 {
    margin: 0;
    font-size: 13px;
    color: var(--muted-foreground);
    font-weight: 500;
  }
  .section-heading h2 a {
    display: flex;
    align-items: center;
    gap: 4px;
    color: inherit;
    text-decoration: none;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .resource-link {
    display: flex;
    align-items: center;
    gap: 11px;
    min-height: 53px;
    padding: 10px 3px;
    color: var(--foreground);
    text-decoration: none;
    font-size: 13px;
    border-radius: 5px;
  }
  .resource-link > :global(svg) {
    color: var(--muted-foreground);
    flex-shrink: 0;
  }
  .resource-link > :global(svg:last-child) {
    margin-left: auto;
    width: 12px;
  }
  .resource-copy {
    display: flex;
    flex-direction: column;
    min-width: 0;
    gap: 3px;
  }
  .resource-title {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .resource-detail {
    font-size: 11px;
    color: var(--muted-foreground);
  }
  .shortcut-list li + li {
    border-top: 1px solid var(--border);
  }
  .resource-link:hover,
  .agent-pill:hover {
    background: var(--muted);
  }
  .empty-list {
    padding: 14px 3px;
    color: var(--muted-foreground);
    font-size: 13px;
    line-height: 1.7;
  }
  .empty-list > :global(svg) {
    opacity: 0.65;
  }
  .empty-list p {
    margin: 12px 0;
    max-width: 240px;
  }
  .empty-list a {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    text-decoration: none;
    color: var(--foreground);
    font-size: 12px;
  }
  .list-message {
    color: var(--muted-foreground);
    font-size: 13px;
    padding-top: 12px;
  }
  .list-message :global(button) {
    padding-left: 0;
  }
  a:focus-visible,
  .agent-pill:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 4px;
  }
  @media (max-width: 760px) {
    .home-page {
      padding-top: 36px;
    }
    .home-columns {
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }
    .home-columns section:last-child {
      grid-column: 1 / -1;
    }
  }
  @media (max-width: 480px) {
    .home-page {
      padding: 28px 20px 40px;
    }
    .home-columns {
      grid-template-columns: 1fr;
      gap: 28px;
      margin-bottom: 32px;
    }
    .home-intro {
      margin-bottom: 28px;
    }
  }
</style>
