<script lang="ts">
  import { untrack } from 'svelte';
  import {
    Plus,
    Search,
    RefreshCw,
    ChevronRight,
    GitBranch,
    MessageSquarePlus,
    Archive,
    Pencil,
    Square,
    RotateCcw,
  } from '@lucide/svelte';
  import type { AgentSession } from '../lib/agent-sessions-api';
  import type { WorkspaceTask } from '../lib/workspace-tasks-api';
  import { taskConversations, taskActivity, conversationStatus } from '../lib/workspace-task-view';
  import { workspace, explain } from '../svelte-lib/context';

  let {
    projectId,
    activeTaskId,
    activeSessionId,
    onSelectTask,
    onOpenSession,
    onNewChat,
    repositoryEnabled,
    canCreate,
    canChat,
    canReadChats = true,
    onTasksChange,
  }: {
    projectId: string;
    activeTaskId?: string;
    activeSessionId?: string;
    onSelectTask: (task?: WorkspaceTask) => Promise<boolean>;
    onOpenSession: (session: AgentSession) => void;
    onNewChat: (task?: WorkspaceTask) => void;
    repositoryEnabled: boolean;
    canCreate: boolean;
    canChat: boolean;
    canReadChats?: boolean;
    onTasksChange?: (items: WorkspaceTask[]) => void;
  } = $props();
  const { agents, tasks: api, query } = workspace();
  let tasks = $state<WorkspaceTask[]>([]);
  let sessions = $state<AgentSession[]>([]);
  let search = $state('');
  let expanded = $state(new Set<string>(['shared']));
  let archivedOpen = $state(false);
  let newTaskOpen = $state(false);
  let titleDraft = $state('');
  let editing = $state('');
  let renameDraft = $state('');
  let taskCursor = $state<string>();
  let sessionCursor = $state<string>();
  let loading = $state(true);
  let busy = $state('');
  let listError = $state('');
  let createError = $state('');
  let errors = $state<Record<string, string>>({});
  let version = 0;
  let taskPages = 1;
  let sessionPages = 1;
  let request: { title: string; id: string } | undefined;
  let refreshing = false;
  const branchLabel = (branch: string) =>
    branch.replace(
      /^(tasks|sessions)\/([0-9a-f-]{36})$/,
      (_match, prefix: string, id: string) => `${prefix}/${id.slice(0, 8)}`,
    );
  const matches = (text: string) => text.toLowerCase().includes(search.trim().toLowerCase());
  const chats = (id?: string) => taskConversations(sessions, id);
  const visibleChats = (task?: WorkspaceTask) =>
    chats(task?.id).filter(
      (session) =>
        !search.trim() ||
        matches(task?.title || 'Shared workspace') ||
        matches(`${session.title || 'Untitled conversation'} ${session.agent_display_name}`),
    );
  const taskMatches = (task: WorkspaceTask) =>
    matches(`${task.title} ${task.branch}`) || visibleChats(task).length > 0;
  const currentTasks = $derived(
    tasks.filter((task) => !task.archived_at && (!search.trim() || taskMatches(task))),
  );
  const archivedTasks = $derived(
    tasks.filter((task) => task.archived_at && (!search.trim() || taskMatches(task))),
  );
  const canCancel = (session: AgentSession) =>
    session.latest_run &&
    ['QUEUED', 'CLAIMED', 'RUNNING'].includes(session.latest_run.status) &&
    !session.latest_run.cancel_requested_at;
  const canResume = (session: AgentSession) =>
    canChat &&
    session.status !== 'ARCHIVED' &&
    session.latest_run &&
    ['CANCELLED', 'FAILED', 'TIMED_OUT'].includes(session.latest_run.status);

  async function refresh(id: string, generation: number) {
    if (refreshing) return;
    refreshing = true;
    try {
      const [taskResult, sessionResult] = await Promise.allSettled([
        (async () => {
          if (!repositoryEnabled || !api)
            return { items: [] as WorkspaceTask[], cursor: undefined };
          let cursor: string | undefined;
          const items: WorkspaceTask[] = [];
          for (let i = 0; i < taskPages; i += 1) {
            const page = await api.list(id, cursor);
            items.push(...page.items);
            cursor = page.nextCursor;
            if (!cursor) break;
          }
          return { items, cursor };
        })(),
        (async () => {
          if (!canReadChats) return { items: [] as AgentSession[], cursor: undefined };
          let cursor: string | undefined;
          const items: AgentSession[] = [];
          for (let i = 0; i < sessionPages; i += 1) {
            const page = await agents.listSessions(id, cursor);
            items.push(...page.items);
            cursor = page.nextCursor;
            if (!cursor) break;
          }
          return { items, cursor };
        })(),
      ]);
      if (generation !== version) return;
      const failures: string[] = [];
      if (taskResult.status === 'fulfilled') {
        tasks = taskResult.value.items;
        taskCursor = taskResult.value.cursor;
      } else failures.push(`Tasks: ${explain(taskResult.reason)}`);
      if (sessionResult.status === 'fulfilled') {
        sessions = sessionResult.value.items;
        sessionCursor = sessionResult.value.cursor;
      } else failures.push(`Conversations: ${explain(sessionResult.reason)}`);
      listError = failures.join(' ');
    } finally {
      if (generation === version) {
        loading = false;
        refreshing = false;
      }
    }
  }
  $effect(() => {
    const id = projectId;
    const generation = ++version;
    tasks = [];
    sessions = [];
    taskCursor = undefined;
    sessionCursor = undefined;
    taskPages = 1;
    sessionPages = 1;
    refreshing = false;
    loading = true;
    search = '';
    expanded = new Set(['shared']);
    errors = {};
    createError = '';
    listError = '';
    newTaskOpen = false;
    editing = '';
    titleDraft = '';
    request = undefined;
    void refresh(id, generation);
    const timer = setInterval(() => void refresh(id, generation), 5000);
    return () => {
      version += 1;
      clearInterval(timer);
    };
  });
  $effect(() => {
    const items = tasks;
    untrack(() => onTasksChange?.(items));
  });
  async function select(task?: WorkspaceTask) {
    const key = task?.id || 'shared';
    const generation = version;
    errors = { ...errors, [key]: '' };
    try {
      if ((await onSelectTask(task)) && generation === version)
        expanded = new Set([...expanded, key]);
    } catch (reason) {
      if (generation === version) errors = { ...errors, [key]: explain(reason) };
    }
  }
  function toggle(key: string) {
    expanded = new Set(
      expanded.has(key) ? [...expanded].filter((id) => id !== key) : [...expanded, key],
    );
  }
  async function create(event: SubmitEvent) {
    event.preventDefault();
    if (!api || !canCreate || !repositoryEnabled || busy || !titleDraft.trim()) return;
    const title = titleDraft.trim();
    if (request?.title !== title) request = { title, id: crypto.randomUUID() };
    const generation = version;
    busy = 'create';
    createError = '';
    try {
      const task = await api.create(projectId, title, request.id);
      if (generation !== version) return;
      tasks = [task, ...tasks.filter((item) => item.id !== task.id)];
      titleDraft = '';
      newTaskOpen = false;
      request = undefined;
      await select(task);
    } catch (reason) {
      if (generation === version) createError = explain(reason);
    } finally {
      if (generation === version) busy = '';
    }
  }
  async function update(task: WorkspaceTask, input: { title?: string; archived?: boolean }) {
    if (!api || busy) return;
    const generation = version;
    busy = task.id;
    errors = { ...errors, [task.id]: '' };
    try {
      const saved = await api.update(projectId, task.id, input);
      if (generation !== version) return;
      tasks = tasks.map((item) => (item.id === task.id ? saved : item));
      editing = '';
    } catch (reason) {
      if (generation === version)
        errors = {
          ...errors,
          [task.id]:
            (reason as { code?: string })?.code === 'repository_task_active' ||
            (reason as { code?: string })?.code === 'task_active'
              ? 'This task has an active run. Wait for it to finish before archiving.'
              : explain(reason),
        };
    } finally {
      if (generation === version) busy = '';
    }
  }
  async function cancel(session: AgentSession) {
    if (!canCancel(session) || busy) return;
    const generation = version;
    busy = session.id;
    errors = { ...errors, [`session:${session.id}`]: '' };
    try {
      await agents.cancelRun(session.latest_run!.id);
      if (generation !== version) return;
      await query.invalidateQueries({ queryKey: ['session-runs', session.id] });
      await refresh(projectId, generation);
    } catch (reason) {
      if (generation === version)
        errors = { ...errors, [`session:${session.id}`]: explain(reason) };
    } finally {
      if (generation === version) busy = '';
    }
  }
</script>

<aside class="workspace-tasks" aria-label="Workspace tasks">
  <div class="actions">
    <button
      class="new-task"
      disabled={!api || !canCreate || !repositoryEnabled}
      onclick={() => (newTaskOpen = !newTaskOpen)}><Plus size={15} />New task</button
    ><button
      class="icon-button"
      aria-label="Refresh tasks"
      disabled={loading}
      onclick={() => refresh(projectId, version)}><RefreshCw size={14} /></button
    >
  </div>
  {#if !repositoryEnabled}<p class="hint">
      File storage is unavailable. Tasks need a working copy.
    </p>{/if}
  {#if newTaskOpen}<form class="task-form" onsubmit={create}>
      <label
        >Task name<input
          maxlength={300}
          required
          bind:value={titleDraft}
          placeholder="e.g. Prove the spectral bound"
        /></label
      >
      <div class="form-actions">
        <button type="submit" disabled={Boolean(busy) || !titleDraft.trim()}
          >{busy === 'create' ? 'Creating…' : 'Create task'}</button
        ><button type="button" disabled={Boolean(busy)} onclick={() => (newTaskOpen = false)}
          >Cancel</button
        >
      </div>
      {#if createError}<p class="error" role="alert">{createError}</p>{/if}
    </form>{/if}
  <label class="search"
    ><Search size={14} /><input
      aria-label="Search tasks and conversations"
      placeholder="Search tasks and chats…"
      bind:value={search}
    /></label
  >
  <p class="hint">Tasks share files; conversations stay private.</p>
  {#if listError}<p class="error" role="alert">
      {listError}<button onclick={() => refresh(projectId, version)}>Retry</button>
    </p>{/if}
  <div class="task-list" aria-busy={loading}>
    {@render taskRow(undefined)}
    {#if loading && !tasks.length}<p class="hint" role="status">Loading tasks…</p>{/if}
    {#each currentTasks as task (task.id)}{@render taskRow(task)}{/each}
    {#if archivedTasks.length}<button
        class="archived-toggle"
        aria-expanded={archivedOpen}
        onclick={() => (archivedOpen = !archivedOpen)}
        ><ChevronRight size={13} class={archivedOpen ? 'expanded' : ''} />Archived tasks ({archivedTasks.length})</button
      >{#if archivedOpen}{#each archivedTasks as task (task.id)}{@render taskRow(
            task,
          )}{/each}{/if}{/if}
    {#if search && !currentTasks.length && !archivedTasks.length && !visibleChats().length && !matches('Shared workspace')}<p
        class="hint"
      >
        No matching tasks or conversations.
      </p>{/if}
    {#if taskCursor}<button
        class="load-more"
        disabled={loading}
        onclick={() => {
          taskPages += 1;
          loading = true;
          void refresh(projectId, version);
        }}>Load more tasks</button
      >{/if}
    {#if sessionCursor}<button
        class="load-more"
        disabled={loading}
        onclick={() => {
          sessionPages += 1;
          loading = true;
          void refresh(projectId, version);
        }}>Load more conversations</button
      >{/if}
  </div>
</aside>

{#snippet taskRow(task?: WorkspaceTask)}
  {@const key = task?.id || 'shared'}
  {@const open =
    expanded.has(key) || Boolean(search.trim()) || Boolean(task && task.id === activeTaskId)}
  {@const conversations = visibleChats(task)}
  {@const activity = taskActivity(chats(task?.id))}
  <section
    class="task"
    class:selected={(task?.id || undefined) === activeTaskId}
    aria-label={task?.title || 'Shared workspace'}
  >
    <div class="task-heading">
      <button
        class="disclosure icon-button"
        aria-label={`Toggle ${task?.title || 'Shared workspace'} conversations`}
        aria-expanded={open}
        onclick={() => toggle(key)}
        ><ChevronRight size={13} class={open ? 'expanded' : ''} /></button
      ><button
        class="select-task"
        aria-label={task?.title || 'Shared workspace'}
        aria-current={(task?.id || undefined) === activeTaskId ? 'true' : undefined}
        onclick={() => select(task)}
        ><strong>{task?.title || 'Shared workspace'}</strong><span
          class="branch"
          title={task?.branch || 'main'}
          ><GitBranch size={10} /><span>{branchLabel(task?.branch || 'main')}</span></span
        ></button
      >
    </div>
    {#if activity}<p class="activity">{activity} in your loaded conversations</p>{/if}
    {#if errors[key]}<p class="error" role="alert">{errors[key]}</p>{/if}
    {#if open}<div class="conversations">
        {#each conversations as session (session.id)}<div
            class="conversation"
            class:active={session.id === activeSessionId}
          >
            <button
              class="open-conversation"
              aria-label={`${session.title || 'Untitled conversation'} ${session.agent_display_name} ${conversationStatus(session)}`}
              onclick={() => onOpenSession(session)}
              aria-current={session.id === activeSessionId ? 'true' : undefined}
              ><span>{session.title || 'Untitled conversation'}</span><small
                >{session.agent_display_name} · {conversationStatus(session)}</small
              ></button
            >{#if canCancel(session)}<button
                class="run-action"
                disabled={Boolean(busy)}
                aria-label={`Cancel run for ${session.title || 'Untitled conversation'}`}
                onclick={() => cancel(session)}><Square size={10} />Cancel</button
              >{:else if canResume(session)}<button
                class="run-action"
                aria-label={`Resume run for ${session.title || 'Untitled conversation'}`}
                onclick={() => onOpenSession(session)}><RotateCcw size={11} />Resume in chat</button
              >{/if}{#if errors[`session:${session.id}`]}<p class="error" role="alert">
                {errors[`session:${session.id}`]}
              </p>{/if}
          </div>{/each}
        {#if canChat && !task?.archived_at}<button
            class="new-conversation"
            onclick={() => onNewChat(task)}><MessageSquarePlus size={13} />New conversation</button
          >{/if}
        {#if task && canCreate}<div class="task-tools">
            {#if editing === task.id}<form
                class="task-form"
                onsubmit={(event) => {
                  event.preventDefault();
                  if (renameDraft.trim()) void update(task, { title: renameDraft.trim() });
                }}
              >
                <label>Rename task<input required maxlength={300} bind:value={renameDraft} /></label
                >
                <div class="form-actions">
                  <button disabled={Boolean(busy) || !renameDraft.trim()}>Save name</button><button
                    type="button"
                    onclick={() => (editing = '')}>Cancel</button
                  >
                </div>
              </form>{:else}<button
                class="run-action"
                aria-label={`Rename ${task.title}`}
                onclick={() => {
                  editing = task.id;
                  renameDraft = task.title;
                }}><Pencil size={11} />Rename</button
              ><button
                class="run-action"
                disabled={Boolean(busy) ||
                  chats(task.id).some(
                    (session) =>
                      session.latest_run &&
                      ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(
                        session.latest_run.status,
                      ),
                  )}
                title="Active runs must finish before archiving"
                aria-label={`${task.archived_at ? 'Restore' : 'Archive'} ${task.title}`}
                onclick={() => update(task, { archived: !task.archived_at })}
                ><Archive size={11} />{task.archived_at ? 'Restore' : 'Archive'}</button
              >{/if}
          </div>{/if}
      </div>{/if}
  </section>
{/snippet}

<style>
  .workspace-tasks {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    padding: 12px;
    gap: 10px;
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
  .actions,
  .search,
  .task-heading,
  .form-actions,
  .branch,
  .task-tools {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 7px;
  }
  .new-task {
    flex: 1;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 8px;
    font-size: 12px;
    background: var(--background);
  }
  .icon-button {
    padding: 5px;
    border: 0;
    background: transparent;
    color: var(--muted-foreground);
  }
  .search {
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 7px;
    color: var(--muted-foreground);
  }
  input {
    width: 100%;
    min-width: 0;
    font-size: 12px;
    background: transparent;
    color: var(--foreground);
  }
  .search input {
    border: 0;
  }
  .hint {
    margin: 0;
    font-size: 10px;
    line-height: 1.5;
    color: var(--muted-foreground);
  }
  .task-list {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }
  .task {
    margin-bottom: 6px;
    padding: 6px 2px;
    border-radius: 7px;
  }
  .selected {
    background: var(--sidebar-accent);
  }
  .task-heading {
    align-items: flex-start;
  }
  .select-task {
    display: flex;
    flex-direction: column;
    gap: 4px;
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
  .branch {
    max-width: 100%;
    min-width: 0;
    color: var(--muted-foreground);
    font-size: 10px;
    overflow-wrap: anywhere;
  }
  .branch span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .branch :global(svg) {
    flex-shrink: 0;
  }
  :global(.workspace-tasks .expanded) {
    transform: rotate(90deg);
  }
  .activity {
    font-size: 10px;
    color: var(--primary);
    margin: 5px 0 5px 28px;
  }
  .conversations {
    margin: 5px 0 0 23px;
    border-left: 1px solid var(--border);
    padding-left: 8px;
  }
  .conversation {
    border-radius: 5px;
    margin-bottom: 4px;
  }
  .active {
    background: var(--background);
    color: var(--primary);
  }
  .open-conversation {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
    text-align: left;
    border: 0;
    background: transparent;
    padding: 6px;
    font-size: 11px;
  }
  .open-conversation span {
    overflow-wrap: anywhere;
  }
  small {
    color: var(--muted-foreground);
    font-size: 10px;
  }
  .run-action,
  .new-conversation {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px;
    border: 0;
    background: transparent;
    font-size: 10px;
    color: var(--muted-foreground);
  }
  .new-conversation {
    color: var(--foreground);
    margin-top: 5px;
  }
  .task-form {
    display: flex;
    flex-direction: column;
    gap: 7px;
    padding: 6px;
    font-size: 11px;
  }
  .task-form label {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .task-form input {
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 5px;
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
  .load-more,
  .archived-toggle {
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
