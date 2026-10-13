<script lang="ts">
  import { untrack } from 'svelte';
  import ProjectPanelHeader from './ProjectPanelHeader.svelte';
  import { Plus, ChevronRight, GitBranch, MessageSquarePlus } from '@lucide/svelte';
  import type { AgentSession } from '../lib/agent-sessions-api';
  import type { ProjectTask as Worktree } from '../lib/project-tasks-api';
  import { projectContext, explain } from '../svelte-lib/context';

  let {
    projectId,
    activeWorktreeId,
    activeSessionId,
    repositoryEnabled,
    canCreate,
    canChat,
    canReadChats,
    onSelectWorktree,
    onOpenSession,
    onNewChat,
    onWorktreesChange,
  }: {
    projectId: string;
    activeWorktreeId?: string;
    activeSessionId?: string;
    repositoryEnabled: boolean;
    canCreate: boolean;
    canChat: boolean;
    canReadChats: boolean;
    onSelectWorktree: (worktree?: Worktree) => Promise<boolean>;
    onOpenSession: (id: string) => void;
    onNewChat: (worktree?: Worktree) => void;
    onWorktreesChange: (items: Worktree[]) => void;
  } = $props();
  const { tasks: api, agents } = projectContext();
  let worktrees = $state<Worktree[]>([]);
  let sessions = $state<AgentSession[]>([]);
  let expanded = $state(new Set<string>(['main']));
  let archivedOpen = $state(false);
  let createOpen = $state(false);
  let name = $state('');
  let branchName = $state('');
  let startBranch = $state('main');
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let actionError = $state('');
  let worktreeCursor = $state<string>();
  let sessionCursor = $state<string>();
  let generation = 0;
  let worktreePages = 1;
  let sessionPages = 1;
  let fetching = false;
  let request: { name: string; id: string } | undefined;
  const current = $derived(
    worktrees
      .filter((item) => !item.archived_at)
      .sort((a, b) => Number(b.branch === 'main') - Number(a.branch === 'main')),
  );
  const archived = $derived(worktrees.filter((item) => item.archived_at));
  const conversations = (id?: string) =>
    sessions
      .filter(
        (session) =>
          (session.worktree_id ||
            session.task_id ||
            worktrees.find((tree) => tree.branch === 'main')?.id) === id,
      )
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));

  async function refresh(id: string, version: number) {
    if (fetching) return;
    fetching = true;
    try {
      const results = await Promise.allSettled([
        (async () => {
          const items: Worktree[] = [];
          let cursor: string | undefined;
          if (api && repositoryEnabled)
            for (let i = 0; i < worktreePages; i++) {
              const page = await api.list(id, cursor);
              items.push(...page.items);
              cursor = page.nextCursor;
              if (!cursor) break;
            }
          return { items, cursor };
        })(),
        (async () => {
          const items: AgentSession[] = [];
          let cursor: string | undefined;
          if (canReadChats)
            for (let i = 0; i < sessionPages; i++) {
              const page = await agents.listSessions(id, cursor);
              items.push(...page.items);
              cursor = page.nextCursor;
              if (!cursor) break;
            }
          return { items, cursor };
        })(),
      ]);
      if (version !== generation) return;
      const [trees, chats] = results;
      const errors: string[] = [];
      if (trees.status === 'fulfilled') {
        worktrees = trees.value.items;
        worktreeCursor = trees.value.cursor;
      } else errors.push(explain(trees.reason));
      if (chats.status === 'fulfilled') {
        sessions = chats.value.items;
        sessionCursor = chats.value.cursor;
      } else errors.push(explain(chats.reason));
      error = errors.join(' ');
    } finally {
      if (version === generation) {
        loading = false;
        fetching = false;
      }
    }
  }
  $effect(() => {
    const id = projectId;
    // Retry when repository availability arrives after the first render.
    const available = repositoryEnabled;
    const readable = canReadChats;
    untrack(() => {
      void available;
      void readable;
      generation++;
      worktreePages = 1;
      sessionPages = 1;
      fetching = false;
      loading = true;
      worktrees = [];
      sessions = [];
      worktreeCursor = undefined;
      sessionCursor = undefined;
      expanded = new Set(['main']);
      name = '';
      createOpen = false;
      busy = false;
      archivedOpen = false;
      request = undefined;
      actionError = '';
      void refresh(id, generation);
    });
    const version = generation;
    const timer = setInterval(() => void refresh(id, version), 5000);
    return () => {
      generation++;
      clearInterval(timer);
    };
  });
  $effect(() => {
    const items = worktrees;
    untrack(() => onWorktreesChange(items));
  });
  $effect(() => {
    const key = activeWorktreeId || 'main';
    untrack(() => {
      expanded = new Set([...expanded, key]);
    });
  });
  async function select(worktree?: Worktree) {
    const version = generation;
    actionError = '';
    try {
      if ((await onSelectWorktree(worktree)) && version === generation)
        expanded = new Set([...expanded, worktree?.id || 'main']);
    } catch (reason) {
      if (version === generation) actionError = explain(reason);
    }
  }
  async function create(event: SubmitEvent) {
    event.preventDefault();
    if (!api || !repositoryEnabled || !canCreate || busy || !name.trim()) return;
    const version = generation;
    const title = name.trim();
    const signature = JSON.stringify([title, branchName, startBranch]);
    if (request?.name !== signature) request = { name: signature, id: crypto.randomUUID() };
    busy = true;
    actionError = '';
    try {
      const saved = await api.create(projectId, title, request.id, branchName, startBranch);
      if (version !== generation) return;
      worktrees = [saved, ...worktrees.filter((item) => item.id !== saved.id)];
      name = '';
      createOpen = false;
      busy = false;
      archivedOpen = false;
      request = undefined;
      await select(saved);
    } catch (reason) {
      if (version === generation) actionError = explain(reason);
    } finally {
      if (version === generation) busy = false;
    }
  }
  async function restore(worktree: Worktree) {
    if (!api || !canCreate || busy) return;
    const version = generation;
    busy = true;
    actionError = '';
    try {
      const saved = await api.update(projectId, worktree.id, { archived: false });
      if (version !== generation) return;
      worktrees = worktrees.map((item) => (item.id === saved.id ? saved : item));
    } catch (reason) {
      if (version === generation) actionError = explain(reason);
    } finally {
      if (version === generation) busy = false;
    }
  }
  async function removeWorktree(worktree: Worktree) {
    if (!api || busy || !canCreate) return;
    if (
      !confirm(
        `Remove ${worktree.title}?${worktree.changed_files?.length ? ' Saved uncommitted changes will be discarded.' : ''} The branch and conversations will be retained.`,
      )
    )
      return;
    busy = true;
    try {
      const saved = await api.update(projectId, worktree.id, {
        archived: true,
        discard_changes: Boolean(worktree.changed_files?.length),
      });
      worktrees = worktrees.map((item) => (item.id === saved.id ? saved : item));
      if (activeWorktreeId === worktree.id)
        await select(worktrees.find((item) => item.branch === 'main'));
    } catch (cause) {
      actionError = explain(cause);
    } finally {
      busy = false;
    }
  }
  function toggle(key: string) {
    expanded = new Set(
      expanded.has(key) ? [...expanded].filter((id) => id !== key) : [...expanded, key],
    );
  }
</script>

<aside class="worktrees" aria-label="Worktrees">
  <ProjectPanelHeader title="Worktrees">
    {#snippet actions()}
      <button
        class="icon-button"
        aria-label="New worktree"
        title="New worktree"
        disabled={!api || !canCreate || !repositoryEnabled}
        onclick={() => (createOpen = !createOpen)}><Plus size={15} /></button
      >
    {/snippet}
  </ProjectPanelHeader>
  {#if createOpen}<form onsubmit={create}>
      <label
        >Worktree name<input
          required
          maxlength={300}
          bind:value={name}
          oninput={(event) => {
            branchName = event.currentTarget.value
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, '-')
              .replace(/^-|-$/g, '');
          }}
          placeholder="e.g. alternate-proof"
        /></label
      >
      <label>Branch name<input required maxlength={100} bind:value={branchName} /></label>
      <label
        >Start from<select bind:value={startBranch}
          >{#each current as tree (tree.id)}<option value={tree.branch}>{tree.branch}</option
            >{/each}{#if !current.length}<option value="main">main</option>{/if}</select
        ></label
      >
      <div class="form-actions">
        <button disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create worktree'}</button
        ><button type="button" disabled={busy} onclick={() => (createOpen = false)}>Cancel</button>
      </div>
    </form>{/if}
  {#if !repositoryEnabled}<p class="hint">File storage is unavailable.</p>{/if}
  {#if error}<p class="error" role="alert">
      {error}<button onclick={() => refresh(projectId, generation)}>Retry</button>
    </p>{/if}
  {#if actionError}<p class="error" role="alert">{actionError}</p>{/if}
  <div class="tree-list" aria-busy={loading}>
    {#if !worktrees.some((tree) => tree.branch === 'main')}{@render row(undefined)}{/if}
    {#if loading && !worktrees.length}<p class="hint" role="status">Loading worktrees…</p>{/if}
    {#each current as worktree (worktree.id)}{@render row(worktree)}{/each}
    {#if archived.length}<button
        class="load-more"
        aria-expanded={archivedOpen}
        onclick={() => (archivedOpen = !archivedOpen)}
        ><ChevronRight size={13} />Removed worktrees ({archived.length})</button
      >
      {#if archivedOpen}{#each archived as worktree (worktree.id)}{@render row(
            worktree,
          )}{/each}{/if}
    {/if}
    {#if worktreeCursor}<button
        class="load-more"
        disabled={loading}
        onclick={() => {
          worktreePages++;
          loading = true;
          void refresh(projectId, generation);
        }}>Load more worktrees</button
      >{/if}
    {#if sessionCursor}<button
        class="load-more"
        disabled={loading}
        onclick={() => {
          sessionPages++;
          loading = true;
          void refresh(projectId, generation);
        }}>Load more conversations</button
      >{/if}
  </div>
</aside>

{#snippet row(worktree?: Worktree)}
  {@const key = worktree?.id || 'main'}
  {@const title = worktree?.title || 'Main'}
  {@const chats = conversations(worktree?.id)}
  {@const open = expanded.has(key)}
  <section
    class="tree"
    class:selected={(worktree?.id || undefined) === activeWorktreeId}
    aria-label={`${title} worktree`}
  >
    <div class="tree-heading">
      <button
        class="icon-button"
        aria-label={`Toggle ${title} conversations`}
        aria-expanded={open}
        onclick={() => toggle(key)}
        ><ChevronRight size={13} class={open ? 'expanded' : ''} /></button
      >
      <button
        class="select-tree"
        aria-label={`Select ${title} worktree`}
        aria-current={(worktree?.id || undefined) === activeWorktreeId ? 'true' : undefined}
        onclick={() => select(worktree)}><GitBranch size={14} /><strong>{title}</strong></button
      >
      {#if canChat && !worktree?.archived_at}<button
          class="icon-button"
          aria-label={`New conversation in ${title}`}
          title="New conversation"
          onclick={() => onNewChat(worktree)}><MessageSquarePlus size={14} /></button
        >{/if}
    </div>
    {#if worktree?.lifecycle === 'unavailable'}<p class="hint">Checkout unavailable</p>{/if}
    {#if open}<div class="conversations">
        {#each chats as session (session.id)}<button
            class="conversation"
            aria-label={`${session.title || 'Untitled conversation'} ${session.agent_display_name} ${session.latest_run?.status.toLowerCase().replaceAll('_', ' ') || 'Ready'}`}
            class:active={session.id === activeSessionId}
            aria-current={session.id === activeSessionId ? 'true' : undefined}
            onclick={() => onOpenSession(session.id)}
          >
            <span>{session.title || 'Untitled conversation'}</span><small
              >{session.agent_display_name} · {session.latest_run?.status
                .toLowerCase()
                .replaceAll('_', ' ') || 'Ready'}</small
            >
          </button>{/each}
        {#if !chats.length}<p class="hint">
            {canReadChats ? 'No conversations yet.' : 'Conversations are private.'}
          </p>{/if}
        {#if worktree && !worktree.archived_at && worktree.branch !== 'main' && canCreate}<button
            class="load-more"
            disabled={busy || worktree.writable === false}
            onclick={() => removeWorktree(worktree)}>Remove worktree</button
          >{/if}
        {#if worktree && (worktree.archived_at || worktree.lifecycle === 'unavailable') && canCreate}<button
            class="load-more"
            disabled={busy}
            onclick={() => restore(worktree)}>Restore worktree</button
          >{/if}
      </div>{/if}
  </section>
{/snippet}

<style>
  .worktrees {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    padding: 0 12px 12px;
    gap: 12px;
    color: var(--foreground);
  }
  button {
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  button:focus-visible,
  input:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .icon-button {
    display: flex;
    padding: 5px;
    border: 0;
    background: transparent;
    color: var(--muted-foreground);
  }
  .hint {
    margin: 0;
    font-size: 11px;
    line-height: 1.5;
    color: var(--muted-foreground);
  }
  .tree-list {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }
  .tree {
    margin-bottom: 6px;
    padding: 6px 2px;
    border-radius: 7px;
  }
  .selected {
    background: var(--sidebar-accent);
  }
  .tree-heading {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .select-tree {
    display: flex;
    align-items: center;
    gap: 7px;
    text-align: left;
    flex: 1;
    min-width: 0;
    padding: 3px;
    border: 0;
    background: transparent;
  }
  strong {
    font-size: 12px;
    font-weight: 550;
    overflow-wrap: anywhere;
  }
  .select-tree :global(svg) {
    flex-shrink: 0;
    color: var(--muted-foreground);
  }
  :global(.worktrees .expanded) {
    transform: rotate(90deg);
  }
  .conversations {
    margin: 5px 0 0 23px;
    border-left: 1px solid var(--border);
    padding-left: 8px;
  }
  .conversation {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
    text-align: left;
    border: 0;
    background: transparent;
    padding: 6px;
    font-size: 11px;
    border-radius: 5px;
  }
  .conversation span {
    overflow-wrap: anywhere;
  }
  .conversation.active {
    background: var(--background);
    color: var(--primary);
  }
  small {
    color: var(--muted-foreground);
    font-size: 10px;
  }
  form,
  label {
    display: flex;
    flex-direction: column;
    gap: 7px;
    font-size: 11px;
  }
  input {
    width: 100%;
    min-width: 0;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--background);
  }
  .form-actions {
    display: flex;
    gap: 7px;
  }
  .form-actions button {
    padding: 5px;
    border: 1px solid var(--border);
    border-radius: 5px;
  }
  .error {
    color: var(--destructive);
    font-size: 11px;
    overflow-wrap: anywhere;
  }
  .error button {
    text-decoration: underline;
    margin-left: 5px;
  }
  .load-more {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 8px 3px;
    font-size: 11px;
    color: var(--muted-foreground);
    border: 0;
    background: transparent;
  }
</style>
