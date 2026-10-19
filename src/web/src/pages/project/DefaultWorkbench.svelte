<script lang="ts">
  import ChatWorkbenchShell from './components/ChatWorkbenchShell.svelte';
  import ChatWorkbenchPages from './components/ChatWorkbenchPages.svelte';
  import ProjectFileExplorer from './components/ProjectFileExplorer.svelte';

  import { onMount, setContext, untrack } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { projectContext, contextKey, explain } from '../../svelte-lib/context';
  import type { ObjectVersion } from '../../lib/research-api';
  import type { Activity } from '../../lib/history-api';
  import type { ProjectMap } from '../../lib/project-map';
  import ProjectSectionPanel from './components/ProjectSectionPanel.svelte';
  import ProjectObjectPanel from './components/ProjectObjectPanel.svelte';
  import type { Project } from '../../lib/research-api';
  import type { AgentSession } from '../../lib/agent-sessions-api';
  import { createDefaultFilesApi, type DefaultFiles } from '../../lib/default-files-api';
  import { bytesToBase64 } from '../../lib/repository-api';
  import { projectRouteTab, type ProjectTab } from '../../lib/project-tabs';
  import { canWriteResearch } from '../../lib/access';
  import { Info, FileText } from '@lucide/svelte';
  import ProjectToolsHeader from './components/ProjectToolsHeader.svelte';
  import DefaultFileEditor from './components/DefaultFileEditor.svelte';
  let { project }: { project: Project; path: string } = $props();
  const context = projectContext();
  setContext(contextKey, {
    ...context,
    repository: undefined,
    tasks: undefined,
    linear: undefined,
    defaultFiles: true,
  });
  const api = createDefaultFilesApi({ getAccessToken: context.auth.token });
  let workspace = $state<DefaultFiles>();
  let shell = $state<ChatWorkbenchShell>();
  let tabs = $state<ProjectTab[]>([]);
  let sessions = $state<AgentSession[]>([]);
  let chatsLoaded = $state(false);
  let chatsError = $state('');
  let moreChats = $state(false);
  let chatsLoading = $state(false);
  let chatPages = 1;
  let chatsGeneration = 0;
  async function refreshChats() {
    if (chatsLoading) return;
    const generation = chatsGeneration;
    chatsLoading = true;
    try {
      const items: AgentSession[] = [];
      let cursor: string | undefined;
      for (let i = 0; i < chatPages; i++) {
        const result = await context.agents.listSessions(project.id, cursor);
        items.push(...result.items);
        cursor = result.nextCursor;
        if (!cursor) break;
      }
      if (generation !== chatsGeneration) return;
      sessions = items;
      moreChats = Boolean(cursor);
      chatsLoaded = true;
      chatsError = '';
    } catch (cause) {
      if (generation === chatsGeneration) chatsError = explain(cause);
    } finally {
      if (generation === chatsGeneration) chatsLoading = false;
    }
  }
  onMount(() => {
    void refreshChats();
    const interval = setInterval(() => void refreshChats(), 5000);
    return () => {
      chatsGeneration++;
      clearInterval(interval);
    };
  });
  let fileVisible = $state(false);
  let lastChatHref = $state('');
  let rightMode = $state('file');
  let error = $state('');
  let fileBusy = $state(false);
  let selectedResearch = $state<{ version: ObjectVersion; searchResult: boolean }>();
  let selectedActivity = $state<Activity>();
  let mapData = $state<ProjectMap>();
  let mapObjectId = $state('');
  let mapPanelTab = $state('body');
  const active = $derived(projectRouteTab(project.id, page.url.pathname + page.url.search));
  const section = $derived(page.url.pathname.split('/')[3] || 'overview');
  const entity = $derived(page.url.pathname.split('/')[4]);
  $effect(() => {
    if (['sessions', 'files', 'overview'].includes(section)) rightMode = 'file';
  });
  let filePath = $state('');
  let fileEditor = $state<DefaultFileEditor>();
  const activeId = $derived(active?.id || '');
  const canChat = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  const draftChats = $derived(
    tabs.filter(
      (item) =>
        item.kind === 'chat' && new URL(item.href, 'http://local').pathname.endsWith('/new'),
    ),
  );
  $effect(() => {
    const pathname = page.url.pathname;
    if (pathname === `/projects/${project.id}` || pathname === `/projects/${project.id}/sessions`) {
      void goto(
        untrack(
          () => lastChatHref || `/projects/${project.id}/${canChat ? 'sessions/new' : 'overview'}`,
        ),
        { replaceState: true },
      );
      return;
    }
    if (pathname === `/projects/${project.id}/files`) {
      const name = page.url.searchParams.get('file');
      untrack(() => {
        if (name) openFile(name);
        void goto(
          lastChatHref || `/projects/${project.id}/${canChat ? 'sessions/new' : 'overview'}`,
          { replaceState: true },
        );
      });
      return;
    }
    const tab = projectRouteTab(project.id, pathname + page.url.search);
    if (tab && section !== 'files')
      untrack(() => {
        if (!tabs.some((item) => item.id === tab.id)) tabs = [...tabs, tab];
        if (tab.kind === 'chat') lastChatHref = tab.href;
      });
  });
  async function attempt(action: () => Promise<unknown>) {
    error = '';
    try {
      await action();
    } catch (cause) {
      error = explain(cause);
    }
  }
  async function refreshFiles() {
    workspace = await api.list(project.id);
  }
  function navigate(href: string) {
    if (fileVisible && fileEditor && !fileEditor.canClose()) return;
    fileVisible = false;
    shell?.closeDrawer();
    void goto(href);
  }

  function newChat() {
    navigate(`/projects/${project.id}/sessions/new?draft=${crypto.randomUUID()}`);
  }
  function openFile(name: string) {
    fileVisible = true;
    rightMode = 'file';
    shell?.showPanel('tools');
    if (name !== filePath && fileEditor && !fileEditor.canClose()) return;
    filePath = name;
  }
  async function createFile(name: string, content_base64: string) {
    if (fileBusy) return false;
    fileBusy = true;
    await attempt(async () => {
      await api.command(project.id, { action: 'write', path: name, content_base64 });
      await refreshFiles();
      openFile(name);
    });
    fileBusy = false;
    return !error;
  }
  async function upload(file: File) {
    await attempt(async () => {
      if (file.size > 700_000) throw new Error('Uploads must be no larger than 700 KB.');
      await createFile(file.name, bytesToBase64(new Uint8Array(await file.arrayBuffer())));
    });
  }
  onMount(() => {
    void attempt(refreshFiles);
    const interval = setInterval(() => {
      void attempt(refreshFiles);
    }, 5000);
    return () => clearInterval(interval);
  });
</script>

<ChatWorkbenchShell
  bind:this={shell}
  {project}
  {section}
  {entity}
  {activeId}
  {canChat}
  {draftChats}
  {sessions}
  {chatsLoaded}
  {chatsError}
  {chatsLoading}
  {moreChats}
  {navigate}
  {newChat}
  {refreshChats}
  loadMore={() => {
    chatPages++;
    void refreshChats();
  }}
>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if fileVisible}
    {#if filePath}<DefaultFileEditor
        bind:this={fileEditor}
        projectId={project.id}
        path={filePath}
        writable={canChat && Boolean(workspace?.writable)}
        onChanged={(name) => {
          void attempt(refreshFiles);
          if (name !== undefined) filePath = name;
          if (name === '') rightMode = 'file';
        }}
      />{/if}
  {/if}
  <div class="chat-pages" hidden={fileVisible}>
    <ChatWorkbenchPages
      {project}
      bind:tabs
      {activeId}
      bind:selectedResearch
      bind:selectedActivity
      bind:mapData
      bind:mapObjectId
      bind:mapPanelTab
      onCreated={(id) => {
        navigate(`/projects/${project.id}/sessions/${id}`);
        void refreshChats();
      }}
      onInspect={() => {
        if (section === 'sessions') return;
        rightMode = 'details';
        shell?.showPanel('tools');
      }}
    />
  </div>

  {#snippet right(placement)}
    <ProjectToolsHeader
      items={[
        ['file', 'File', FileText],
        ...(section !== 'sessions' && section !== 'files' && section !== 'overview'
          ? [['details', 'Details', Info] as const]
          : []),
      ]}
      value={rightMode}
      onselect={(value) => (rightMode = value)}
      {placement}
      onclose={() => shell?.closePanel('tools', placement)}
    />
    <div class="tool-content">
      {#if rightMode === 'file'}<p class="tool-empty">Open a file from Files to edit it.</p>
        {#if !filePath}<p class="tool-empty">Choose a file from Files in the left sidebar.</p>{/if}
      {/if}
      {#if rightMode === 'details'}
        {#if section === 'objects' && entity}<ProjectObjectPanel
            projectId={project.id}
            objectId={entity}
            publicRead={false}
          />
        {:else}<ProjectSectionPanel
            {project}
            {section}
            bind:selected={selectedActivity}
            bind:selectedResearch
            {mapData}
            bind:mapObjectId
            bind:mapPanelTab
          />{/if}
      {/if}
    </div>
  {/snippet}
  {#snippet files()}
    <ProjectFileExplorer
      paths={workspace?.files.map((file) => file.path) ?? []}
      selected={filePath}
      writable={canChat && Boolean(workspace?.writable)}
      loaded={Boolean(workspace)}
      onopen={openFile}
      oncreate={(name) => createFile(name, '')}
      onupload={upload}
    />
  {/snippet}
</ChatWorkbenchShell>

<style>
  .tool-content {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .tool-empty {
    padding: 16px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .chat-pages {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }
  .chat-pages[hidden] {
    display: none;
  }
</style>
