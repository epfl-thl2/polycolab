<script lang="ts">
  import FeedbackToast from '../../../ui/FeedbackToast.svelte';
  import { MessageSquarePlus, Square, RotateCcw } from '@lucide/svelte';
  import {
    createProjectConversations,
    projectConversationItems,
    invalidateConversation,
  } from '../../../lib/conversation-queries';
  import type { Conversation } from '../../../lib/conversations-api';
  import { projectContext, explain } from '../../../svelte-lib/context';

  let {
    projectId,
    activeConversationId,
    onOpenConversation,
    onNewChat,
    canChat = true,
    canReadChats = true,
  }: {
    projectId: string;
    activeConversationId?: string;
    onOpenConversation: (id: string) => void;
    onNewChat: () => void;
    canChat?: boolean;
    canReadChats?: boolean;
  } = $props();
  const { agents, query } = projectContext();
  const chats = createProjectConversations(
    agents,
    () => projectId,
    () => canReadChats,
    query,
  );
  const conversations = $derived(canReadChats ? projectConversationItems($chats.data) : []);
  const loading = $derived(canReadChats && ($chats.isPending || $chats.isFetchingNextPage));
  const error = $derived(canReadChats && $chats.isError ? explain($chats.error) : '');
  const cursor = $derived(canReadChats && $chats.hasNextPage);
  let actionError = $state<{ conversationId: string; message: string }>();
  let cancelling = $state('');
  const cancellable = (conversation: Conversation) =>
    conversation.latest_execution?.can_interrupt &&
    ['QUEUED', 'CLAIMED', 'RUNNING'].includes(conversation.latest_execution.status) &&
    !conversation.latest_execution.cancel_requested_at;
  const resumable = (conversation: Conversation) =>
    conversation.status !== 'archived' &&
    conversation.capabilities.can_send &&
    conversation.latest_execution &&
    ['CANCELLED', 'FAILED', 'TIMED_OUT'].includes(conversation.latest_execution.status);
  const title = (conversation: Conversation) => conversation.title?.trim() || 'Untitled chat';
  const status = (conversation: Conversation) =>
    conversation.latest_execution?.cancel_requested_at &&
    ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(conversation.latest_execution.status)
      ? 'Cancelling'
      : (conversation.latest_execution?.status ?? conversation.status)
          .toLowerCase()
          .replaceAll('_', ' ');
  const visible = $derived(
    [...conversations].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)),
  );

  async function cancel(conversation: Conversation) {
    if (!cancellable(conversation) || cancelling) return;
    const id = projectId;
    cancelling = conversation.id;
    actionError = undefined;
    try {
      await agents.cancelRun(conversation.id, conversation.latest_execution!.id);
      if (id !== projectId) return;
      await query.invalidateQueries({ queryKey: ['conversation-runs', conversation.id] });
      await invalidateConversation(query, id, conversation.id);
    } catch (reason) {
      if (id === projectId)
        actionError = { conversationId: conversation.id, message: explain(reason) };
    } finally {
      cancelling = '';
    }
  }
</script>

<FeedbackToast message={actionError?.message || ''} variant={actionError ? 'error' : 'success'} />

<aside class="project-agents" aria-label="Conversations">
  <div class="agent-actions">
    <h2>Conversations</h2>
    {#if canChat}<button class="new-chat" aria-label="New conversation" onclick={onNewChat}
        ><MessageSquarePlus size={16} /></button
      >{/if}
  </div>
  <FeedbackToast
    message={error}
    variant="error"
    action={{ label: 'Retry', run: () => $chats.refetch() }}
  />
  <div class="conversation-list" aria-busy={loading}>
    {#if loading && !conversations.length}<p class="empty" role="status">Loading chats…</p>
    {:else if !visible.length}<p class="empty">
        {error
          ? 'Conversations unavailable.'
          : canReadChats
            ? 'No conversations yet.'
            : 'Conversations are unavailable for your role.'}
      </p>{/if}
    {#each visible as conversation (conversation.id)}
      <div class="conversation" class:selected={conversation.id === activeConversationId}>
        <button
          class="open-conversation"
          onclick={() => onOpenConversation(conversation.id)}
          aria-current={conversation.id === activeConversationId ? 'true' : undefined}
        >
          <span class="conversation-title">{title(conversation)}</span>
          <span class="agent-name">{conversation.configuration?.display_name}</span>
          <span
            class="run-status"
            class:running={Boolean(
              conversation.latest_execution &&
              ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(
                conversation.latest_execution.status,
              ),
            )}><span class="status-dot"></span>{status(conversation)}</span
          >
        </button>
        {#if cancellable(conversation)}<button
            class="run-action"
            aria-label={`Cancel run for ${title(conversation)}`}
            disabled={Boolean(cancelling)}
            onclick={() => cancel(conversation)}
            ><Square size={11} />{cancelling === conversation.id ? 'Cancelling…' : 'Cancel'}</button
          >
        {:else if canChat && resumable(conversation)}<button
            class="run-action"
            aria-label={`Resume run for ${title(conversation)}`}
            title="Open this chat to choose an AI provider and resume the run"
            onclick={() => onOpenConversation(conversation.id)}
            ><RotateCcw size={12} />Resume in chat</button
          >{/if}
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
  .conversation-list {
    min-height: 0;
    overflow-y: auto;
    flex: 1;
  }
  .conversation {
    margin-bottom: 5px;
    padding: 2px;
    border-radius: 8px;
  }
  .selected {
    background: var(--brand-soft);
    box-shadow: inset 2px 0 var(--primary);
  }
  .conversation:hover {
    background: var(--brand-soft);
  }
  .open-conversation {
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
  .conversation-title {
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
</style>
