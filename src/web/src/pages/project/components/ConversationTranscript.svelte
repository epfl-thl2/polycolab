<script lang="ts">
  import { Wrench } from '@lucide/svelte';
  import type { ConversationItem } from '../../../lib/conversations-api';
  import ConversationTranscriptItem from './ConversationTranscriptItem.svelte';

  let {
    items,
    ownerId,
    viewerId,
    agentName,
  }: {
    items: ConversationItem[];
    ownerId?: string;
    viewerId?: string;
    agentName?: string;
  } = $props();
  const groups = $derived.by(() => {
    const result: { id: string; activity: boolean; items: ConversationItem[] }[] = [];
    for (const item of items) {
      const activity = item.type === 'tool_call' || item.type === 'tool_result';
      const previous = result.at(-1);
      if (activity && previous?.activity && previous.items[0].execution_id === item.execution_id) {
        previous.items.push(item);
      } else result.push({ id: item.id, activity, items: [item] });
    }
    return result;
  });
</script>

<div class="transcript">
  {#each groups as group (group.id)}
    {#if group.activity}
      <details class="chat-activity">
        <summary
          ><Wrench size={14} aria-hidden="true" />
          <span
            >Tool activity <span class="chat-activity-count"
              >· {group.items.filter((item) => item.type === 'tool_call').length ||
                group.items.length}
              {group.items.filter((item) => item.type === 'tool_call').length === 1 ||
              group.items.length === 1
                ? 'step'
                : 'steps'}</span
            ></span
          >
        </summary>
        <div class="chat-activity-steps">
          {#each group.items as item (item.id)}
            <ConversationTranscriptItem {item} {ownerId} {viewerId} {agentName} />
          {/each}
        </div>
      </details>
    {:else}
      <ConversationTranscriptItem item={group.items[0]} {ownerId} {viewerId} {agentName} />
    {/if}
  {/each}
</div>
