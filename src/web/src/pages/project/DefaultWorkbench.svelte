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
  import { createProjectSessions, projectSessionItems } from '../../lib/session-queries';
  import { createDefaultFilesApi, type DefaultFiles } from '../../lib/default-files-api';
  import { bytesToBase64 } from '../../lib/repository-api';
  import { projectRouteTab, type ProjectTab } from '../../lib/project-tabs';
  import { canWriteResearch } from '../../lib/access';
  import { Info, FileText } from '@lucide/svelte';
  import ProjectToolsHeader from './components/ProjectToolsHeader.svelte';
  import SidebarFileView from './components/SidebarFileView.svelte';
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
  const chats = createProjectSessions(context.agents, () => project.id);
  const sessions = $derived(projectSessionItems($chats.data));
  const chatsLoaded = $derived(!$chats.isPending);
  const chatsError = $derived($chats.isError ? explain($chats.error) : '');
  const moreChats = $derived($chats.hasNextPage);
  const chatsLoading = $derived($chats.isFetching);
  async function refreshChats() {
    await $chats.refetch();
  }
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
    shell?.closeDrawer();
    void goto(href);
  }

  function newChat() {
    navigate(`/projects/${project.id}/sessions/new?draft=${crypto.randomUUID()}`);
  }
  function openFile(name: string) {
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
    void $chats.fetchNextPage();
  }}
>
  {#if error}<p role="alert">{error}</p>{/if}
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
    }}
    onInspect={() => {
      if (section === 'sessions') return;
      rightMode = 'details';
      shell?.showPanel('tools');
    }}
  />

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
      {#if rightMode === 'file'}<div class="file-host" data-file-panel-host={placement}></div>
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

<SidebarFileView active={rightMode === 'file'}>
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
</SidebarFileView>

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
  .file-host {
    height: 100%;
    min-height: 0;
  }
</style>
