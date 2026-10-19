<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { Project } from '../../../lib/research-api';
  import type { AgentSession } from '../../../lib/agent-sessions-api';
  import type { ProjectTab } from '../../../lib/project-tabs';
  import { projectContext } from '../../../svelte-lib/context';
  import { Button } from '../../../lib/components/ui/button';
  import { MessageSquarePlus, PanelLeftClose } from '@lucide/svelte';
  import { untrack } from 'svelte';
  import { sessionTitles } from '../../../lib/session-queries';
  import { projectDialogs } from '../project-dialogs';
  import ProjectShell from './ProjectShell.svelte';
  import ProjectNavigationRail from './ProjectNavigationRail.svelte';
  import ProjectPanelHeader from './ProjectPanelHeader.svelte';
  let {
    project,
    section,
    entity,
    activeId,
    canChat,
    draftChats,
    sessions,
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
    activeId: string;
    canChat: boolean;
    draftChats: ProjectTab[];
    sessions: AgentSession[];
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
  const titles = sessionTitles(
    context.query,
    untrack(() => project.id),
  );
  const dialogs = projectDialogs();
  let leftMode = $state<'chats' | 'files'>('chats');
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
  projectName={project.name}
  leftTitle={leftMode === 'files' ? 'Files' : 'Conversations'}
  leftLabel={leftMode === 'files' ? 'Project files' : 'Conversations'}
  showProjectName={false}
  plainTopBar={true}
  {right}
>
  {#snippet toolbar()}
    <div class="chat-title">
      {#if section === 'sessions' && entity && entity !== 'new'}
        {$titles[entity] || ''}
      {/if}
    </div>
  {/snippet}
  {#snippet navigation(expanded)}<ProjectNavigationRail
      auth={context.auth}
      projectId={project.id}
      section={['files', 'sessions', 'objects'].includes(section) ? 'sessions' : section}
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
      <div class="conversations" hidden={leftMode !== 'chats'}>{@render conversations()}</div>
      <div class="files" hidden={leftMode !== 'files'}>{@render files()}</div>
    </div>{/snippet}
  <div class="chat-content">{@render children()}</div>
</ProjectShell>
{#snippet conversations()}
  {#if canChat}<div class="new-chat">
      <Button variant="outline" onclick={newChat}><MessageSquarePlus size={16} />New chat</Button>
    </div>{/if}
  {#if chatsError}<p role="alert">{chatsError}</p>
    <Button variant="ghost" onclick={refreshChats}>Retry conversations</Button>{/if}
  {#if !chatsLoaded && !chatsError}<p class="muted">Loading conversations…</p>{/if}
  <nav aria-label="Your conversations">
    <h3>Your conversations</h3>
    {#each draftChats as draft (draft.id)}<a
        href={draft.href}
        aria-current={activeId === draft.id ? 'page' : undefined}
        onclick={(event) => openChat(event, draft.href)}
        ><span>New chat</span><small>Draft</small></a
      >{/each}
    {#each sessions.filter((item) => item.can_control) as session (session.id)}
      {@const href = `/projects/${project.id}/sessions/${session.id}`}
      <a
        {href}
        aria-current={entity === session.id && section === 'sessions' ? 'page' : undefined}
        onclick={(event) => openChat(event, href)}
        ><span>{$titles[session.id] || session.title || session.agent_display_name}</span
        >{#if session.is_shared}<small>Shared</small>{/if}</a
      >
    {/each}
    {#if chatsLoaded && !draftChats.length && !sessions.some((item) => item.can_control)}<p
        class="muted"
      >
        Your conversations will appear here.
      </p>{/if}
  </nav>
  {#if sessions.some((item) => !item.can_control)}<nav aria-label="Shared conversations">
      <h3>Shared with you</h3>
      {#each sessions.filter((item) => !item.can_control) as session (session.id)}
        {@const href = `/projects/${project.id}/sessions/${session.id}`}
        <a
          {href}
          aria-current={entity === session.id && section === 'sessions' ? 'page' : undefined}
          onclick={(event) => openChat(event, href)}
          >{$titles[session.id] || session.title || session.agent_display_name}</a
        >
      {/each}
    </nav>{/if}
  {#if moreChats}<Button variant="ghost" disabled={chatsLoading} onclick={loadMore}
      >Load more conversations</Button
    >{/if}
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
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .new-chat {
    padding: 16px 0 8px;
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
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: auto;
    background: var(--sidebar);
    font-size: 12px;
  }
  .conversations a {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px;
    border-radius: 4px;
  }
  .conversations a[aria-current='page'],
  .conversations a:hover {
    background: var(--sidebar-accent);
  }
  .chat-content {
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: auto;
  }
  h3 {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .muted,
  small {
    color: var(--muted-foreground);
  }
  small {
    display: block;
  }
</style>
