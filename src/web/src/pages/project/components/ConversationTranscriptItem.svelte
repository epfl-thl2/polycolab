<script lang="ts">
  import Markdown from '../../../ui/Markdown.svelte';
  import type { ConversationItem } from '../../../lib/conversations-api';

  let {
    item,
    ownerId,
    agentName,
  }: { item: ConversationItem; ownerId?: string; agentName?: string } = $props();
  const author = $derived(
    item.author.type === 'human'
      ? `${item.author.user_id === ownerId ? 'Conversation owner' : 'Participant'} · ${item.author.user_id.slice(0, 8)}`
      : item.author.type === 'agent'
        ? item.author.display_name ||
          (item.author.agent_version_id ? agentName || 'Agent' : 'Assistant')
        : item.author.type === 'tool'
          ? item.author.name
          : 'System',
  );
</script>

<article class="message" class:user={item.author.type === 'human'} data-item-type={item.type}>
  <p class="message-author">{author}</p>
  {#if item.type === 'message'}
    <div class="message-body"><Markdown content={item.data.content_md} /></div>
  {:else if item.type === 'tool_call'}
    <p>Tool call · <code>{item.data.name}</code></p>
  {:else if item.type === 'tool_result'}
    <p>Tool result · <code>{item.data.name}</code> · {item.data.outcome}</p>
  {:else}
    <p role="status">Execution stopped · {item.data.code.replaceAll('_', ' ')}</p>
  {/if}
  {#if item.status !== 'completed'}<small>{item.status.replaceAll('_', ' ')}</small>{/if}
</article>

<style>
  .message {
    margin: 16px 0;
    min-width: 0;
  }
  .message-author {
    color: var(--muted-foreground);
    font-size: 12px;
    margin-bottom: 6px;
  }
  .message-body {
    overflow-wrap: anywhere;
  }
  .user {
    background: var(--muted);
    border-radius: 10px;
    padding: 12px 16px;
  }
</style>
