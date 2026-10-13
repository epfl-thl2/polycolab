<script lang="ts">
  import { onMount, setContext, untrack } from 'svelte';
  import { page } from '$app/state';
  import { beforeNavigate, goto } from '$app/navigation';
  import { projectContext, contextKey, explain } from '../svelte-lib/context';
  import type { Project } from '../lib/research-api';
  import type { AgentSession } from '../lib/agent-sessions-api';
  import type { LinearCheckpoint, LinearDocument } from '../lib/linear-api';
  import { LinearSession } from '../lib/linear-session';
  import { bytesToBase64 } from '../lib/repository-api';
  import { projectRouteTab, type ProjectTab } from '../lib/project-tabs';
  import { ProjectEditorSessions } from '../lib/project-editor-session';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import FileExplorer from './FileExplorer.svelte';
  import MonacoSourceEditor from './MonacoSourceEditor.svelte';
  import LinearGitArchive from './LinearGitArchive.svelte';
  import LinearBatches from './LinearBatches.svelte';
  import Markdown from './Markdown.svelte';
  import ProjectTabStrip from './ProjectTabStrip.svelte';
  import ProjectNavigationRail from './ProjectNavigationRail.svelte';
  import ProjectPage from './ProjectPage.svelte';
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
  const peers = $derived.by(() => {
    void revision;
    return [...live.peers];
  });
  const recovery = $derived.by(() => {
    void revision;
    return [...live.recovery];
  });
  const activity = $derived.by(() => {
    void revision;
    return live.activity;
  });
  const editorSessions = new ProjectEditorSessions();
  let tabs = $state<ProjectTab[]>([]);
  let activeId = $state('');
  let sessions = $state<AgentSession[]>([]);
  let error = $state('');
  let newPath = $state('');
  let checkpointTitle = $state('');
  let history = $state(false);
  let historyDiff = $state('');
  let checkpoints = $state<LinearCheckpoint[]>([]);
  let historical = $state<LinearDocument[]>([]);
  let selectedCheckpoint = $state<LinearCheckpoint>();
  let preview = $state(false);
  let fallback = $state(false);
  let text = $state('');
  let rename = $state('');
  const current = $derived.by(() => {
    void revision;
    const opened = live.documents.get(activeId);
    return opened ? { ...opened, value: { ...opened.value } } : undefined;
  });
  const active = $derived(tabs.find((tab) => tab.id === activeId));
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
    const tab = projectRouteTab(project.id, page.url.pathname + page.url.search);
    if (
      tab &&
      !['files'].includes(new URL(path, 'http://local').pathname.split('/')[3] ?? 'overview')
    ) {
      untrack(() => {
        if (!tabs.some((t) => t.id === tab.id)) tabs = [...tabs, tab];
        activeId = tab.id;
      });
    }
  });
  $effect(() => {
    const files = workspace?.files;
    if (!files) return;
    untrack(() => {
      tabs = tabs.map((tab) => {
        const file = files.find((file) => file.id === tab.id);
        return file
          ? {
              ...tab,
              label: file.path.split('/').at(-1)!,
              href: `/projects/${project.id}/files?file=${encodeURIComponent(file.path)}`,
            }
          : tab;
      });
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
  async function refreshChats() {
    sessions = (await context.agents.listSessions(project.id)).items;
  }
  onMount(() => {
    void attempt(async () => {
      await live.start();
      const file = new URL(location.href).searchParams.get('file');
      if (file) await openFile(file);
    });
    void attempt(refreshChats);
    const interval = setInterval(() => void refreshChats().catch(() => {}), 5000);
    const unload = (event: BeforeUnloadEvent) => {
      if (live.saving) event.preventDefault();
    };
    window.addEventListener('beforeunload', unload);
    return () => {
      clearInterval(interval);
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
  async function openFile(filePath: string, mode: 'preview' | 'permanent' = 'permanent') {
    const file = workspace?.files.find((item) => item.path === filePath);
    if (!file) return;
    await attempt(async () => {
      await live.open(file.id);
      if (!tabs.some((t) => t.id === file.id))
        tabs = [
          ...tabs.filter((t) => !t.preview),
          {
            id: file.id,
            kind: 'file',
            label: filePath.split('/').at(-1)!,
            href: `/projects/${project.id}/files?file=${encodeURIComponent(filePath)}`,
            preview: mode === 'preview',
          },
        ];
      activeId = file.id;
      revision++;
    });
  }
  function pin() {
    tabs = tabs.map((tab) => (tab.id === activeId ? { ...tab, preview: false } : tab));
  }
  async function close(id: string) {
    await attempt(async () => {
      await live.flush();
      tabs = tabs.filter((t) => t.id !== id);
      if (activeId === id) activeId = tabs.at(-1)?.id ?? '';
    });
  }
  function newChat() {
    void goto(`/projects/${project.id}/sessions/new?draft=${crypto.randomUUID()}`);
  }
  async function createFile() {
    await attempt(async () => {
      await live.command([
        { kind: 'create', file_id: crypto.randomUUID(), path: newPath, content_base64: '' },
      ]);
      newPath = '';
    });
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
    pin();
  }
  async function upload(event: Event) {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
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
<div class="linear-shell">
  <ProjectNavigationRail
    auth={context.auth}
    projectId={project.id}
    section={path.split('/')[3] ?? 'overview'}
    canManage={project.current_user_role === 'OWNER'}
    onNavigate={(href) => void goto(href)}
  />
  <aside aria-label="Conversations">
    <h2>{project.name}</h2>
    <p class="muted">Linear history</p>
    {#if project.current_user_role !== 'READ_ONLY'}<Button onclick={newChat}>New chat</Button>{/if}
    {#if workspace?.has_git_archive}<LinearGitArchive projectId={project.id} />{/if}
    <LinearBatches projectId={project.id} {live} />
    <details>
      <summary>People here</summary>{#each peers as peer (peer.connection_id)}<p>
          {peer.label}{peer.file_id
            ? ` · ${workspace?.files.find((f) => f.id === peer.file_id)?.path ?? 'Editing'}`
            : ''}
        </p>{/each}
    </details>
    <h3>Your conversations</h3>
    {#each sessions.filter((s) => s.can_control) as session (session.id)}<a
        href={`/projects/${project.id}/sessions/${session.id}`}
        >{session.title || session.agent_display_name}{session.is_shared ? ' · Shared' : ''}</a
      >{/each}
    <h3>Shared with you</h3>
    {#each sessions.filter((s) => !s.can_control) as session (session.id)}<a
        href={`/projects/${project.id}/sessions/${session.id}`}
        >{session.title || session.agent_display_name}</a
      >{/each}
  </aside>
  <main aria-label="Project workbench">
    <ProjectTabStrip
      {tabs}
      {activeId}
      onselect={(id) => (activeId = id)}
      onclose={(id) => void close(id)}
      onreorder={(ids) => (tabs = ids.flatMap((id) => tabs.find((t) => t.id === id) ?? []))}
      onpin={pin}
      onnewchat={project.current_user_role !== 'READ_ONLY' ? newChat : undefined}
    />
    <div class="save-workspace" role="status">{status}{activity ? ` · ${activity}` : ''}</div>
    {#if error}<p role="alert">{error}</p>{/if}
    {#if recovery.length}<section aria-label="Recovered edits">
        <h3>Unsaved text recovery</h3>
        {#each recovery as [name, content] (name)}<Button onclick={() => download(name, content)}
            >Download {name}</Button
          >{/each}
      </section>{/if}
    {#if current && active?.kind === 'file'}
      <div class="file-actions">
        <span>{current.value.path}</span><Button
          variant="ghost"
          onclick={() => (preview = !preview)}>{preview ? 'Source' : 'Preview'}</Button
        ><Button variant="ghost" onclick={() => (fallback = !fallback)}>Text editor</Button><Button
          variant="ghost"
          onclick={() =>
            download(
              current.value.path,
              current.value.document === null
                ? Uint8Array.from(atob(current.value.content_base64), (c) => c.charCodeAt(0))
                : text,
            )}>Download</Button
        >
      </div>
      {#if current.value.deleted}<p>
          This file was deleted.
        </p>{:else if current.value.document === null}<p>
          Binary file. Download it to inspect its contents.
        </p>{:else if preview}<Markdown content={text} />{:else if fallback}<textarea
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
        ></textarea>{:else}{#key activeId}<MonacoSourceEditor
            bind:value={text}
            {language}
            collaborative={current.doc}
            collaborativeUndo={current.undo}
            sessions={editorSessions}
            sessionKey={`${project.id}/${activeId}`}
            readOnly={!writable}
            onEdit={pin}
            onError={() => (fallback = true)}
          />{/key}{/if}
      {#if writable && !current.value.deleted}<details>
          <summary>File actions</summary><Input
            aria-label="New file path"
            bind:value={rename}
            placeholder={current.value.path}
          /><Button
            onclick={() =>
              attempt(() => live.command([{ kind: 'rename', file_id: activeId, path: rename }]))}
            >Rename</Button
          ><Button
            variant="outline"
            onclick={() => {
              if (confirm(`Delete ${current.value.path}? Its saved history remains recoverable.`))
                void attempt(() => live.command([{ kind: 'delete', file_id: activeId }]));
            }}>Delete file</Button
          >
        </details>{/if}
    {/if}
    {#each tabs.filter((t) => t.kind !== 'file') as tab (tab.id)}<div
        class="page-panel"
        hidden={tab.id !== activeId}
      >
        <ProjectPage
          {project}
          href={tab.href}
          active={tab.id === activeId}
          onState={(update) => {
            if (update.label && update.label !== tab.label)
              tabs = tabs.map((t) =>
                t.id === tab.id ? { ...t, label: update.label!, dirty: update.dirty } : t,
              );
          }}
          onCreated={(id) => {
            tabs = tabs.filter((t) => t.id !== tab.id);
            void goto(`/projects/${project.id}/sessions/${id}`);
          }}
          onInspect={() => {}}
        />
      </div>{/each}
    {#if !active}<p class="empty">Open a file or start a conversation.</p>{/if}
  </main>
  <aside aria-label="Project files and history">
    <div class="row">
      <Button variant="ghost" onclick={() => (history = false)}>Files</Button><Button
        variant="ghost"
        onclick={() =>
          attempt(async () => {
            history = true;
            checkpoints = await live.api.checkpoints(project.id);
          })}>History</Button
      >
    </div>
    {#if history}
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
    {:else}
      <FileExplorer
        paths={workspace?.files.map((f) => f.path) ?? []}
        selected={current?.value.path}
        onopen={(name, mode) => void openFile(name, mode)}
      />
      {#if writable}<form
          onsubmit={(event) => {
            event.preventDefault();
            void createFile();
          }}
        >
          <Input aria-label="File path" bind:value={newPath} placeholder="notes.md" /><Button
            type="submit"
            disabled={!newPath}>New file</Button
          >
        </form>
        <label>Upload file<input type="file" onchange={upload} /></label>{/if}
    {/if}
  </aside>
</div>

<style>
  .linear-shell {
    display: grid;
    grid-template-columns: 56px 230px minmax(0, 1fr) 280px;
    height: 100dvh;
    background: var(--background);
  }
  aside {
    padding: 1rem;
    overflow: auto;
    border-right: 1px solid var(--border);
  }
  aside:last-child {
    border-left: 1px solid var(--border);
    border-right: 0;
  }
  aside a {
    display: block;
    padding: 0.5rem 0;
  }
  main {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: auto;
  }
  .page-panel {
    min-height: 0;
    overflow: auto;
    flex: 1;
    padding: 1rem;
  }
  .page-panel[hidden] {
    display: none;
  }
  .save-workspace,
  .file-actions {
    padding: 0.4rem 0.8rem;
    border-bottom: 1px solid var(--border);
    font-size: 0.8rem;
  }
  .file-actions {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }
  .file-actions span {
    flex: 1;
  }
  h2 {
    font-size: 1rem;
  }
  h3 {
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  .muted,
  small {
    color: var(--muted-foreground);
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
  }
  textarea {
    flex: 1;
    padding: 1rem;
    font-family: monospace;
  }
  .empty {
    padding: 3rem;
    color: var(--muted-foreground);
  }
  pre {
    overflow: auto;
    font-size: 0.75rem;
  }
  @media (max-width: 950px) {
    .linear-shell {
      grid-template-columns: 48px minmax(0, 1fr) 220px;
    }
    aside:first-of-type {
      display: none;
    }
  }
  @media (max-width: 600px) {
    .linear-shell {
      grid-template-columns: 40px minmax(0, 1fr);
    }
    aside:last-child {
      grid-column: 2;
      max-height: 30dvh;
    }
  }
</style>
