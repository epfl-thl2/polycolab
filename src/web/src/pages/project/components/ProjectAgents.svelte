<script lang="ts">
  import { MessageSquarePlus, Square, RotateCcw } from '@lucide/svelte';
  import {
    createProjectSessions,
    projectSessionItems,
    invalidateSession,
  } from '../../../lib/session-queries';
  import type { AgentSession } from '../../../lib/agent-sessions-api';
  import { projectContext, explain } from '../../../svelte-lib/context';

  let {
    projectId,
    activeSessionId,
    onOpenSession,
    onNewChat,
    canChat = true,
    canReadChats = true,
  }: {
    projectId: string;
    activeSessionId?: string;
    onOpenSession: (id: string) => void;
    onNewChat: () => void;
    canChat?: boolean;
    canReadChats?: boolean;
  } = $props();
  const { agents, query } = projectContext();
  const chats = createProjectSessions(
    agents,
    () => projectId,
    () => canReadChats,
    query,
  );
  const sessions = $derived(canReadChats ? projectSessionItems($chats.data) : []);
  const loading = $derived(canReadChats && ($chats.isPending || $chats.isFetchingNextPage));
  const error = $derived(canReadChats && $chats.isError ? explain($chats.error) : '');
  const cursor = $derived(canReadChats && $chats.hasNextPage);
  let actionError = $state<{ sessionId: string; message: string }>();
  let cancelling = $state('');
  const cancellable = (session: AgentSession) =>
    session.latest_run &&
    ['QUEUED', 'CLAIMED', 'RUNNING'].includes(session.latest_run.status) &&
    !session.latest_run.cancel_requested_at;
  const resumable = (session: AgentSession) =>
    session.status !== 'ARCHIVED' &&
    session.latest_run &&
    ['CANCELLED', 'FAILED', 'TIMED_OUT'].includes(session.latest_run.status);
  const title = (session: AgentSession) => session.title?.trim() || 'Untitled chat';
  const status = (session: AgentSession) =>
    session.latest_run?.cancel_requested_at &&
    ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(session.latest_run.status)
      ? 'Cancelling'
      : (session.latest_run?.status ?? session.status).toLowerCase().replaceAll('_', ' ');
  const visible = $derived(
    [...sessions].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)),
  );

  async function cancel(session: AgentSession) {
    if (!cancellable(session) || cancelling) return;
    const id = projectId;
    cancelling = session.id;
    actionError = undefined;
    try {
      await agents.cancelRun(session.latest_run!.id);
      if (id !== projectId) return;
      await query.invalidateQueries({ queryKey: ['session-runs', session.id] });
      await invalidateSession(query, id, session.id);
    } catch (reason) {
      if (id === projectId) actionError = { sessionId: session.id, message: explain(reason) };
    } finally {
      cancelling = '';
    }
  }
</script>

<aside class="project-agents" aria-label="Conversations">
  <div class="agent-actions">
    <h2>Conversations</h2>
    {#if canChat}<button class="new-chat" aria-label="New conversation" onclick={onNewChat}
        ><MessageSquarePlus size={16} /></button
      >{/if}
  </div>
  {#if error}<div class="panel-error" role="alert">
      {error}<button onclick={() => $chats.refetch()}>Retry</button>
    </div>{/if}
  <div class="session-list" aria-busy={loading}>
    {#if loading && !sessions.length}<p class="empty" role="status">Loading chats…</p>
    {:else if !visible.length}<p class="empty">
        {canReadChats ? 'No conversations yet.' : 'Conversations are unavailable for your role.'}
      </p>{/if}
    {#each visible as session (session.id)}
      <div class="session" class:selected={session.id === activeSessionId}>
        <button
          class="open-session"
          onclick={() => onOpenSession(session.id)}
          aria-current={session.id === activeSessionId ? 'true' : undefined}
        >
          <span class="session-title">{title(session)}</span>
          <span class="agent-name">{session.agent_display_name}</span>
          <span
            class="run-status"
            class:running={Boolean(
              session.latest_run &&
              ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(session.latest_run.status),
            )}><span class="status-dot"></span>{status(session)}</span
          >
        </button>
        {#if cancellable(session)}<button
            class="run-action"
            aria-label={`Cancel run for ${title(session)}`}
            disabled={Boolean(cancelling)}
            onclick={() => cancel(session)}
            ><Square size={11} />{cancelling === session.id ? 'Cancelling…' : 'Cancel'}</button
          >
        {:else if canChat && resumable(session)}<button
            class="run-action"
            aria-label={`Resume run for ${title(session)}`}
            title="Open this chat to choose an AI provider and resume the run"
            onclick={() => onOpenSession(session.id)}><RotateCcw size={12} />Resume in chat</button
          >{/if}
        {#if actionError?.sessionId === session.id}<p class="panel-error" role="alert">
            {actionError.message}
          </p>{/if}
      </div>
    {/each}
    {#if cursor}<button class="load-more" disabled={loading} onclick={() => $chats.fetchNextPage()}
        >{loading ? 'Loading…' : 'Load more chats'}</button
      >{/if}
  </div>
</aside>

<style>
  .project-agents {
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: 100%;
    min-width: 0;
    height: 100%;
    min-height: 0;
    padding: 16px 12px;
    color: var(--foreground);
    background: var(--sidebar, var(--background));
  }
  .agent-actions {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  h2 {
    flex: 1;
    margin: 0;
    font-size: 12px;
    font-weight: 550;
  }
  button {
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .new-chat {
    display: flex;
    align-items: center;
    padding: 5px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--muted-foreground);
  }
  .session-list {
    min-height: 0;
    overflow-y: auto;
    flex: 1;
  }
  .session {
    margin-bottom: 5px;
    padding: 2px;
    border-radius: 8px;
  }
  .selected {
    background: var(--brand-soft);
    box-shadow: inset 2px 0 var(--primary);
  }
  .session:hover {
    background: var(--brand-soft);
  }
  .open-session {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
    padding: 8px;
    text-align: left;
    background: transparent;
    border: 0;
    border-radius: 6px;
  }
  .session-title {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 500;
  }
  .agent-name {
    color: var(--muted-foreground);
    font-size: 11px;
  }
  .run-status {
    display: flex;
    gap: 5px;
    align-items: center;
    font-size: 10px;
    color: var(--muted-foreground);
    text-transform: capitalize;
  }
  .status-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: currentColor;
  }
  .running {
    color: var(--accent-strong);
  }
  .run-action {
    display: flex;
    gap: 5px;
    align-items: center;
    margin: 0 8px 6px;
    padding: 3px 0;
    color: var(--muted-foreground);
    border: 0;
    background: transparent;
    font-size: 11px;
  }
  .run-action:hover {
    color: var(--foreground);
  }
  .load-more {
    width: 100%;
    padding: 8px;
    border: 0;
    background: transparent;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .empty {
    padding: 12px 5px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .panel-error {
    margin: 4px 0;
    padding: 8px;
    font-size: 12px;
    color: var(--destructive);
    overflow-wrap: anywhere;
  }
  .panel-error button {
    margin-left: 6px;
    text-decoration: underline;
  }
</style>
