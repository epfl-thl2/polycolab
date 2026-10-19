<script lang="ts">
  import ChatWorkbenchShell from './components/ChatWorkbenchShell.svelte';
  import ChatWorkbenchPages from './components/ChatWorkbenchPages.svelte';
  import ProjectFileExplorer from './components/ProjectFileExplorer.svelte';

  import { onMount, setContext, untrack } from 'svelte';
  import { page } from '$app/state';
  import { beforeNavigate, goto } from '$app/navigation';
  import { projectContext, contextKey, explain } from '../../svelte-lib/context';
  import type { Project } from '../../lib/research-api';
  import { createProjectSessions, projectSessionItems } from '../../lib/session-queries';
  import type { LinearCheckpoint, LinearDocument } from '../../lib/linear-api';
  import { LinearSession } from '../../lib/linear-session';
  import { bytesToBase64 } from '../../lib/repository-api';
  import { projectRouteTab, type ProjectTab } from '../../lib/project-tabs';
  import { ProjectEditorSessions } from '../../lib/project-editor-session';
  import { Button } from '../../lib/components/ui/button';
  import { canWriteResearch } from '../../lib/access';
  import { FileText, FileCheck2, History, Info } from '@lucide/svelte';
  import ProjectToolsHeader from './components/ProjectToolsHeader.svelte';
  import ProjectPanelHeader from './components/ProjectPanelHeader.svelte';
  import ProjectSectionPanel from './components/ProjectSectionPanel.svelte';
  import ProjectObjectPanel from './components/ProjectObjectPanel.svelte';
  import type { ObjectVersion } from '../../lib/research-api';
  import type { Activity } from '../../lib/history-api';
  import type { ProjectMap } from '../../lib/project-map';
  import { Input } from '../../lib/components/ui/input';
  import MonacoSourceEditor from '../../ui/MonacoSourceEditor.svelte';
  import LinearGitArchive from './components/LinearGitArchive.svelte';
  import LinearBatches from './components/LinearBatches.svelte';
  import Markdown from '../../ui/Markdown.svelte';
  import SidebarFileView from './components/SidebarFileView.svelte';
  import ProjectFileView from './components/ProjectFileView.svelte';
  let { project, path }: { project: Project; path: string } = $props();
  const context = projectContext();
  let revision = $state(0);
  const live = new LinearSession(
    untrack(() => project.id),
    context.auth.token,
    () => revision++,
  );
  setContext(contextKey, { ...context, repository: undefined, linear: live });
  const workspace = $derived.by(() => {
    void revision;
    return live.state;
  });
  const writable = $derived.by(() => {
    void revision;
    return live.writable;
  });
  const status = $derived.by(() => {
    void revision;
    return live.error || (!live.connected ? 'Reconnecting…' : live.saving ? 'Saving…' : 'Saved');
  });
  const recovery = $derived.by(() => {
    void revision;
    return [...live.recovery];
  });
  const editorSessions = new ProjectEditorSessions();
  let tabs = $state<ProjectTab[]>([]);
  let activeId = $state('');
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
  let selectionVersion = 0;
  const canChat = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  const draftChats = $derived(
    tabs.filter(
      (item) =>
        item.kind === 'chat' && new URL(item.href, 'http://local').pathname.endsWith('/new'),
    ),
  );

  let error = $state('');
  let checkpointTitle = $state('');
  let rightMode = $state('file');
  const history = $derived(rightMode === 'history');
  let shell = $state<ChatWorkbenchShell>();
  let selectedResearch = $state<{ version: ObjectVersion; searchResult: boolean }>();
  let selectedActivity = $state<Activity>();
  let mapData = $state<ProjectMap>();
  let mapObjectId = $state('');
  let mapPanelTab = $state('body');
  function selectTool(value: string) {
    rightMode = value;
    if (value === 'history')
      void attempt(async () => {
        checkpoints = await live.api.checkpoints(project.id);
      });
  }

  let historyDiff = $state('');
  let checkpoints = $state<LinearCheckpoint[]>([]);
  let historical = $state<LinearDocument[]>([]);
  let selectedCheckpoint = $state<LinearCheckpoint>();
  let mode = $state<'source' | 'preview' | 'changes'>('source');
  let enhanced = $state(true);
  let wordWrap = $state(true);
  let selectedFileId = $state('');
  let text = $state('');
  const current = $derived.by(() => {
    void revision;
    const opened = live.documents.get(selectedFileId);
    return opened ? { ...opened, value: { ...opened.value } } : undefined;
  });
  const active = $derived(tabs.find((tab) => tab.id === activeId));
  const section = $derived(
    active?.kind === 'file'
      ? 'files'
      : new URL(active?.href || path, 'http://local').pathname.split('/')[3] || 'overview',
  );
  const entity = $derived(new URL(active?.href || path, 'http://local').pathname.split('/')[4]);
  const language = $derived(
    current?.value.path.endsWith('.lean')
      ? 'LEAN'
      : current?.value.path.endsWith('.py')
        ? 'PYTHON'
        : current?.value.path.endsWith('.md')
          ? 'MARKDOWN'
          : current?.value.path.endsWith('.json')
            ? 'JSON'
            : 'TEXT',
  );
  $effect(() => {
    live.focus(current?.value.id ?? null);
  });
  $effect(() => {
    void revision;
    if (current) text = current.doc.getText('content').toString();
  });
  $effect(() => {
    const pathname = page.url.pathname;
    if (pathname === `/projects/${project.id}` || pathname === `/projects/${project.id}/sessions`) {
      const destination = untrack(
        () => lastChatHref || `/projects/${project.id}/${canChat ? 'sessions/new' : 'overview'}`,
      );
      void goto(destination, { replaceState: true });
      return;
    }
    if (pathname === `/projects/${project.id}/files`) {
      const name = page.url.searchParams.get('file');
      const file = workspace?.files.find((item) => item.path === name);
      if (name && !workspace) return;
      untrack(() => {
        if (file) openFile(file.path);
        void goto(
          lastChatHref || `/projects/${project.id}/${canChat ? 'sessions/new' : 'overview'}`,
          { replaceState: true },
        );
      });
      return;
    }
    const tab = projectRouteTab(project.id, pathname + page.url.search);
    if (tab)
      untrack(() => {
        if (!tabs.some((item) => item.id === tab.id)) tabs = [...tabs, tab];
        activeId = tab.id;
        if (tab.kind === 'chat') lastChatHref = tab.href;
      });
  });
  async function attempt(action: () => Promise<unknown>) {
    error = '';
    try {
      await action();
    } catch (reason) {
      error = reason instanceof Error ? reason.message : explain(reason);
    }
  }
  function navigate(href: string) {
    shell?.closeDrawer();
    void goto(href);
  }

  onMount(() => {
    void attempt(async () => {
      await live.start();
    });
    const unload = (event: BeforeUnloadEvent) => {
      if (live.saving) event.preventDefault();
    };
    window.addEventListener('beforeunload', unload);
    return () => {
      window.removeEventListener('beforeunload', unload);
      live.destroy();
      editorSessions.dispose();
    };
  });
  beforeNavigate(({ to, cancel }) => {
    if (live.saving && !to?.url.pathname.startsWith(`/projects/${project.id}/`)) {
      cancel();
      error = 'Wait for edits to be saved before leaving.';
    }
  });
  function openFile(filePath: string) {
    rightMode = 'file';
    shell?.showPanel('tools');
    void loadFile(filePath, ++selectionVersion);
  }
  async function loadFile(filePath: string, version: number) {
    const file = workspace?.files.find((item) => item.path === filePath);
    if (!file) return;
    await attempt(async () => {
      await live.open(file.id);
      if (version !== selectionVersion) return;
      selectedFileId = file.id;
      mode = 'source';
      revision++;
    });
  }
  function newChat() {
    navigate(`/projects/${project.id}/sessions/new?draft=${crypto.randomUUID()}`);
  }
  async function createFile(newPath: string) {
    await attempt(async () => {
      await live.command([
        { kind: 'create', file_id: crypto.randomUUID(), path: newPath, content_base64: '' },
      ]);
      openFile(newPath);
    });
    return !error;
  }
  function editPlain(value: string) {
    if (!current || !writable) return;
    const shared = current.doc.getText('content'),
      old = shared.toString();
    let start = 0,
      end = 0;
    while (start < old.length && start < value.length && old[start] === value[start]) start++;
    while (
      end < old.length - start &&
      end < value.length - start &&
      old[old.length - 1 - end] === value[value.length - 1 - end]
    )
      end++;
    current.doc.transact(() => {
      shared.delete(start, old.length - start - end);
      shared.insert(start, value.slice(start, value.length - end));
    }, 'plain-editor');
  }
  async function upload(file: File) {
    await attempt(async () => {
      if (file.size > 700_000) throw new Error('Uploads must be no larger than 700 KB.');
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary: boolean;
      try {
        new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        binary = bytes.includes(0);
      } catch {
        binary = true;
      }
      await live.command([
        {
          kind: 'create',
          file_id: crypto.randomUUID(),
          path: file.name,
          binary,
          content_base64: bytesToBase64(bytes),
        },
      ]);
      openFile(file.name);
    });
  }
  function download(name: string, content: string | Uint8Array<ArrayBuffer>) {
    const url = URL.createObjectURL(new Blob([content]));
    const link = document.createElement('a');
    link.href = url;
    link.download = name.split('/').at(-1)!;
    link.click();
    URL.revokeObjectURL(url);
  }
</script>

<svelte:window
  onkeydown={(event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 's') {
      event.preventDefault();
      void attempt(() => live.flush());
    }
  }}
/>
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
  {#if recovery.length}<section aria-label="Recovered edits">
      <h3>Unsaved text recovery</h3>
      {#each recovery as [name, content] (name)}<Button onclick={() => download(name, content)}
          >Download {name}</Button
        >{/each}
    </section>{/if}
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
      rightMode = 'details';
      shell?.showPanel('tools');
    }}
  />

  {#if !active}<p class="empty">Open a file or start a conversation.</p>{/if}
  {#snippet right(placement)}{@render tools(placement)}{/snippet}
  {#snippet files()}
    <ProjectFileExplorer
      paths={workspace?.files.map((file) => file.path) ?? []}
      selected={current?.value.path}
      {writable}
      loaded={Boolean(workspace)}
      onopen={openFile}
      oncreate={createFile}
      onupload={upload}
    />
  {/snippet}
</ChatWorkbenchShell>

{#snippet tools(placement: 'desktop' | 'mobile')}
  <ProjectToolsHeader
    items={[
      ['file', 'File', FileText],
      ['history', 'History', History],
      ['changes', 'Agent changes', FileCheck2],
      [
        'details',
        section === 'objects' ? 'Details' : 'Agent history',
        section === 'objects' ? Info : History,
      ],
    ]}
    value={rightMode}
    onselect={selectTool}
    {placement}
    onclose={() => {
      shell?.closePanel('tools', placement);
    }}
  />
  <div class="tool-content">
    {#if rightMode === 'file'}<div class="file-host" data-file-panel-host={placement}></div>
      {#if !current}<p class="tool-empty">Choose a file from Files in the left sidebar.</p>{/if}
    {/if}
    <div class="agent-changes" hidden={rightMode !== 'changes'}>
      <LinearBatches projectId={project.id} {live} />
    </div>
    {#if rightMode === 'details'}
      {#if section === 'sessions'}<div data-chat-panel-host={placement}></div>
        {#if !entity || entity === 'new'}<p class="tool-empty">
            Start a conversation to see its agent run history.
          </p>{/if}
      {:else if section === 'objects' && entity}<ProjectObjectPanel
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
    {:else if history}
      <div class="history-content">
        <ProjectPanelHeader title="History" />
        {#if workspace?.has_git_archive}<LinearGitArchive projectId={project.id} />{/if}

        {#if writable}<Input aria-label="Checkpoint name" bind:value={checkpointTitle} /><Button
            onclick={() =>
              attempt(async () => {
                await live.flush();
                await live.api.checkpoint(project.id, checkpointTitle || 'Named checkpoint');
                checkpoints = await live.api.checkpoints(project.id);
                checkpointTitle = '';
              })}>Create checkpoint</Button
          >{/if}
        {#each checkpoints as checkpoint (checkpoint.id)}<button
            class="history-entry"
            onclick={() =>
              attempt(async () => {
                selectedCheckpoint = checkpoint;
                historical = await live.api.checkpointFiles(project.id, checkpoint.id);
                historyDiff = await live.api.checkpointDiff(project.id, checkpoint.id);
              })}
            >{checkpoint.title}<small>{new Date(checkpoint.created_at).toLocaleString()}</small
            ></button
          >{/each}
        {#if selectedCheckpoint}<h3>{selectedCheckpoint.title}</h3>
          <details>
            <summary>Changes since checkpoint</summary>
            <pre>{historyDiff}</pre>
          </details>
          {#each historical as file (file.id)}<details>
              <summary>{file.path}</summary>
              <pre>{new TextDecoder().decode(
                  Uint8Array.from(atob(file.content_base64), (c) => c.charCodeAt(0)),
                )}</pre>
            </details>{/each}{#if workspace?.can_restore}<Button
              onclick={() => {
                if (
                  confirm(
                    'Restore this checkpoint for everyone? Current work will remain in history.',
                  )
                )
                  void attempt(async () => {
                    await live.flush();
                    await live.api.restore(project.id, selectedCheckpoint!.id, workspace!);
                    location.reload();
                  });
              }}>Restore project</Button
            >{/if}{/if}
      </div>
    {/if}
  </div>
{/snippet}

<SidebarFileView active={rightMode === 'file'}>
  {#if current}
    <ProjectFileView
      path={current.value.path}
      bind:mode
      bind:enhanced
      bind:wordWrap
      writable={writable && !current.value.deleted}
      busy={false}
      dirty={status === 'Saving…'}
      {status}
      binary={current.value.document === null}
      onsave={() => {
        void attempt(() => live.flush());
      }}
      onrename={(name) => {
        void attempt(() => live.command([{ kind: 'rename', file_id: selectedFileId, path: name }]));
      }}
      ondelete={() => {
        if (confirm(`Delete ${current.value.path}? Its saved history remains recoverable.`))
          void attempt(() => live.command([{ kind: 'delete', file_id: selectedFileId }]));
      }}
      onerror={(message) => (error = message)}
      download={() =>
        download(
          current.value.path,
          current.value.document === null
            ? Uint8Array.from(atob(current.value.content_base64), (c) => c.charCodeAt(0))
            : text,
        )}
    >
      {#if current.value.deleted}<p>
          This file was deleted.
        </p>{:else if current.value.document === null}<p>
          Binary file. Download it to inspect its contents.
        </p>{:else if mode === 'preview'}<Markdown content={text} />{:else if !enhanced}<textarea
          wrap={wordWrap ? 'soft' : 'off'}
          aria-label="File contents"
          value={text}
          disabled={!writable}
          onkeydown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
              event.preventDefault();
              if (event.shiftKey) current.undo.redo();
              else current.undo.undo();
            }
          }}
          oninput={(event) => editPlain(event.currentTarget.value)}
        ></textarea>{:else}{#key selectedFileId}<MonacoSourceEditor
            bind:value={text}
            {language}
            {wordWrap}
            collaborative={current.doc}
            collaborativeUndo={current.undo}
            sessions={editorSessions}
            sessionKey={`${project.id}/${selectedFileId}`}
            readOnly={!writable}
            onError={() => (enhanced = false)}
          />{/key}{/if}
    </ProjectFileView>
  {/if}
</SidebarFileView>

<style>
  .file-host {
    height: 100%;
    min-height: 0;
  }
  .agent-changes {
    padding: 12px;
    font-size: 12px;
  }
  .agent-changes[hidden] {
    display: none;
  }
  .tool-content {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .history-content {
    padding: 0 12px;
    font-size: 12px;
  }
  .tool-empty {
    padding: 16px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  h3 {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .history-entry {
    display: block;
    text-align: left;
    width: 100%;
    padding: 0.6rem 0;
    border-bottom: 1px solid var(--border);
  }
  small {
    display: block;
    color: var(--muted-foreground);
  }
  .empty {
    padding: 3rem;
    color: var(--muted-foreground);
  }
  pre {
    overflow: auto;
    font-size: 0.75rem;
  }
</style>
