<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Project } from '../../../lib/projects-api';
  import type { Conversation } from '../../../lib/conversations-api';
  import { projectContext } from '../../../svelte-lib/context';
  import { Button } from '../../../lib/components/ui/button';
  import { SquarePen, PanelLeftClose } from '@lucide/svelte';
  import { untrack } from 'svelte';
  import { conversationTitles } from '../../../lib/conversation-queries';
  import { projectDialogs } from '../project-dialogs';
  import ProjectShell from './ProjectShell.svelte';
  import ProjectNavigationRail from './ProjectNavigationRail.svelte';
  import ProjectPanelHeader from './ProjectPanelHeader.svelte';
  let {
    project,
    section,
    entity,
    canChat,
    conversations,
    chatsLoaded,
    chatsError,
    chatsLoading,
    moreChats,
    navigate,
    newChat,
    refreshChats,
    loadMore,
    children,
    right,
    files,
  }: {
    project: Project;
    section: string;
    entity?: string;
    canChat: boolean;
    conversations: Conversation[];
    chatsLoaded: boolean;
    chatsError: string;
    chatsLoading: boolean;
    moreChats: boolean;
    navigate: (href: string) => void;
    newChat: () => void;
    refreshChats: () => Promise<void>;
    loadMore: () => void;
    children: Snippet;
    right: Snippet<['desktop' | 'mobile']>;
    files: Snippet;
  } = $props();
  const context = projectContext();
  const titles = conversationTitles(
    context.query,
    untrack(() => project.id),
  );
  const dialogs = projectDialogs();
  let leftMode = $state<'chats' | 'files'>('chats');
  let rightClosed = $state(true);
  function selectPanel(panel: 'chats' | 'files') {
    leftMode = panel;
    shell?.showPanel('left');
  }
  let shell = $state<ProjectShell>();
  export function closeDrawer() {
    shell?.closeDrawer();
  }
  export function showPanel(side: 'left' | 'tools') {
    shell?.showPanel(side);
  }
  export function closePanel(side: 'left' | 'tools', placement: 'desktop' | 'mobile') {
    shell?.closePanel(side, placement);
  }
  function openChat(event: MouseEvent, href: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    event.preventDefault();
    navigate(href);
  }
</script>

<ProjectShell
  bind:this={shell}
  bind:rightClosed
  projectName={project.name}
  leftTitle={leftMode === 'files' ? 'Files' : 'Conversations'}
  leftLabel={leftMode === 'files' ? 'Project files' : 'Conversations'}
  showProjectName={false}
  plainTopBar={true}
  {right}
>
  {#snippet toolbar()}
    <div class="chat-title">
      {#if section === 'conversations' && entity && entity !== 'new'}
        {$titles[entity] || ''}
      {/if}
    </div>
  {/snippet}
  {#snippet navigation(expanded)}<ProjectNavigationRail
      auth={context.auth}
      projectId={project.id}
      section={['files', 'conversations'].includes(section) ? 'conversations' : section}
      canManage={project.current_user_role === 'OWNER'}
      {expanded}
      selectedPanel={leftMode}
      onSelectPanel={selectPanel}
      onNavigate={navigate}
      onOpenUtility={() => shell?.closeDrawer()}
    />{/snippet}
  {#snippet left(placement)}<div class="left-content">
      <ProjectPanelHeader
        title={project.name}
        onTitleClick={() => {
          dialogs?.open('information');
          shell?.closeDrawer();
        }}
      >
        {#snippet actions()}<Button
            variant="ghost"
            size="icon-sm"
            aria-label="Hide left panel"
            onclick={() => {
              shell?.closePanel('left', placement);
            }}><PanelLeftClose size={14} /></Button
          >{/snippet}
      </ProjectPanelHeader>
      <div class="conversations" hidden={leftMode !== 'chats'}>{@render conversationList()}</div>
      <div class="files" hidden={leftMode !== 'files'}>{@render files()}</div>
    </div>{/snippet}
  <div class="chat-content">{@render children()}</div>
</ProjectShell>
{#snippet conversationList()}
  {#if canChat}<div class="new-chat">
      <Button variant="ghost" onclick={newChat}
        ><SquarePen size={16} aria-hidden="true" />New chat</Button
      >
    </div>{/if}
  <div class="recents">
    <h3>Recents</h3>
    {#if chatsError}<p role="alert">{chatsError}</p>
      <Button variant="ghost" onclick={refreshChats}>Retry conversations</Button>{/if}
    {#if !chatsLoaded && !chatsError}<p class="muted">Loading conversations…</p>{/if}
    <nav aria-label="Recent conversations">
      {#each conversations as conversation (conversation.id)}
        {@const href = `/projects/${project.id}/conversations/${conversation.id}`}
        <a
          {href}
          aria-current={entity === conversation.id && section === 'conversations'
            ? 'page'
            : undefined}
          onclick={(event) => openChat(event, href)}
          ><span
            >{$titles[conversation.id] ||
              conversation.title ||
              conversation.configuration?.display_name}</span
          >{#if conversation.sharing !== 'private'}<small>Shared</small>{/if}</a
        >
      {/each}
      {#if chatsLoaded && !conversations.length}<p class="muted">
          Your recent conversations will appear here.
        </p>{/if}
    </nav>
    {#if moreChats}<Button variant="ghost" disabled={chatsLoading} onclick={loadMore}
        >Load more conversations</Button
      >{/if}
  </div>
{/snippet}

<style>
  .chat-title {
    flex: 1;
    min-width: 0;
    align-self: center;
    padding: 0 12px;
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @media (max-width: 760px) {
    .chat-title {
      display: none;
    }
  }

  .conversations a span {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .new-chat {
    flex-shrink: 0;
    padding: 8px 0;
  }
  .new-chat :global(button) {
    width: 100%;
    justify-content: flex-start;
  }
  .left-content {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    padding: 0 12px;
  }
  .files {
    flex: 1;
    min-height: 0;
    overflow: auto;
    margin-inline: -12px;
  }
  .conversations[hidden],
  .files[hidden] {
    display: none;
  }
  .conversations {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
    background: var(--sidebar);
    font-size: 12px;
  }
  .recents {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .conversations a {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 28px;
    padding: 4px 8px;
    line-height: 20px;
    border-radius: 4px;
    text-decoration: none;
  }
  .conversations a[aria-current='page'],
  .conversations a:hover {
    background: var(--accent);
    text-decoration: none;
  }
  .conversations a:focus-visible {
    outline: 2px solid var(--muted-foreground);
    outline-offset: -2px;
  }
  .conversations a small {
    flex-shrink: 0;
  }
  .chat-content {
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: auto;
  }
  h3 {
    margin: 8px 0;
    padding: 0 8px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .muted,
  small {
    color: var(--muted-foreground);
  }
  small {
    display: block;
  }
</style>
