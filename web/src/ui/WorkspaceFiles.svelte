<script lang="ts">
  import { onMount, untrack, type Snippet } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { beforeNavigate } from '$app/navigation';
  import { workspace, explain } from '../svelte-lib/context';
  import {
    bytesToBase64,
    decodeFile,
    encodeFile,
    type RepositoryState,
    type RepositoryCommit,
    type RepositoryMergePreview,
    type RepositorySave,
    type RepositoryMerge,
  } from '../lib/repository-api';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import MonacoSourceEditor from './MonacoSourceEditor.svelte';
  import FileExplorer from './FileExplorer.svelte';
  import Markdown from './Markdown.svelte';
  import FileDiff from './FileDiff.svelte';
  import {
    FileText,
    FolderOpen,
    GitBranch,
    History,
    Upload,
    Plus,
    X,
    Save,
    Download,
    Trash2,
    ChevronRight,
    Check,
    LockKeyhole,
    Eye,
    Code2,
    GitMerge,
  } from '@lucide/svelte';

  type OpenFile = {
    id: string;
    path: string;
    originalPath: string;
    content: string;
    original: string;
    base: string;
    binary: boolean;
    enhanced: boolean;
  };
  let tabs = $state<OpenFile[]>([]);
  let activeId = $state('');
  let sidebar = $state<'files' | 'agents'>('files');
  let historyOpen = $state(false);
  let previewText = $state(false);
  let renameOpen = $state(false);
  let uploadInput = $state<HTMLInputElement>();
  const dirtyTab = (tab: OpenFile) =>
    tab.content !== tab.original || tab.path !== tab.originalPath || tab.originalPath === '';
  const unsavedCount = $derived(
    tabs.filter((tab) => (tab.id === activeId ? dirty : dirtyTab(tab))).length,
  );
  const fileLabel = (name: string) => name.split('/').at(-1) || 'Untitled';
  const branchLabel = (name: string) =>
    name === 'main'
      ? 'Shared workspace'
      : branchLabels[name] || `Working copy · ${name.split('/').at(-1)?.slice(0, 8)}`;
  function stash() {
    if (!activeId || !editing) return;
    tabs = tabs.map((tab) =>
      tab.id === activeId
        ? { id: activeId, path, originalPath, content, original, base, binary, enhanced }
        : tab,
    );
  }
  function restore(tab: OpenFile) {
    activeId = tab.id;
    ({ path, originalPath, content, original, base, binary, enhanced } = tab);
    editing = true;
    latest = undefined;
    previewText = false;
    renameOpen = !tab.originalPath;
    notice = '';
  }
  async function activate(tab: OpenFile) {
    if (busy) return;
    onFileOpen?.(tab.id);
    if (tab.id === activeId) return;
    stash();
    restore(tab);
    if (
      !dirtyTab(tab) &&
      tab.base !== repoState?.commit &&
      repoState?.files?.some((file) => file.path === tab.originalPath)
    )
      await open(tab.originalPath, false);
  }
  function closeTab(id: string) {
    if (busy) return;
    stash();
    const tab = tabs.find((item) => item.id === id);
    if (!tab || (dirtyTab(tab) && !confirm(`Discard unsaved changes to ${fileLabel(tab.path)}?`)))
      return;
    const index = tabs.findIndex((item) => item.id === id);
    tabs = tabs.filter((item) => item.id !== id);
    if (id === activeId) {
      const next = tabs[Math.min(index, tabs.length - 1)];
      if (next) restore(next);
      else {
        activeId = '';
        editing = false;
      }
    }
  }
  function shortcut(event: KeyboardEvent) {
    if (active && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (editing && dirty && path && !busy && !binary && repoState?.writable) void save();
    }
  }

  let {
    projectId,
    children,
    onFileOpen,
    active = true,
    enabled = $bindable(false),
    busy = $bindable(false),
    branch = $bindable('main'),
    branchLabels = {},
    workspaceTab,
    toolsView,
    view = 'file',
    onTabsChange,
    onOpenView,
    onCloseView,
  }: {
    projectId: string;
    children?: Snippet<[Snippet, Snippet | undefined, Snippet | undefined]>;
    active?: boolean;
    enabled?: boolean;
    busy?: boolean;
    branch?: string;
    branchLabels?: Record<string, string>;
    workspaceTab?: Snippet;
    onFileOpen?: (id?: string) => void;
    toolsView?: 'explorer' | 'source-control';
    view?: 'file' | 'history' | 'merge';
    onTabsChange?: (
      tabs: { id: string; label: string; path: string; dirty: boolean }[],
      activeId: string,
    ) => void;
    onOpenView?: (view: 'history' | 'merge') => void;
    onCloseView?: (view: 'history' | 'merge') => void;
  } = $props();
  $effect(() => {
    const items = tabs.map((tab) => ({
      id: tab.id,
      label: fileLabel(tab.id === activeId ? path : tab.path),
      path: tab.id === activeId ? path : tab.path,
      dirty: tab.id === activeId ? dirty : dirtyTab(tab),
    }));
    const selected = activeId;
    untrack(() => onTabsChange?.(items, selected));
  });
  export function selectWorkspaceFile(id: string) {
    if (busy) return false;
    const tab = tabs.find((item) => item.id === id);
    if (tab) void activate(tab);
    return Boolean(tab);
  }
  export function closeWorkspaceFile(id: string) {
    closeTab(id);
    return !tabs.some((item) => item.id === id);
  }
  export async function openWorkspaceFile(name: string) {
    await open(name);
    onFileOpen?.(activeId);
  }
  export async function selectWorkspaceBranch(name: string) {
    return selectBranch(name, true);
  }
  const api = workspace().repository;
  let repoState = $state<RepositoryState>();
  $effect(() => {
    if (enabled !== Boolean(repoState?.enabled)) enabled = Boolean(repoState?.enabled);
  });
  let path = $state('');
  let originalPath = $state('');
  let content = $state('');
  let original = $state('');
  let base = $state('');
  let editing = $state(false);
  let binary = $state(false);
  let enhanced = $state(false);
  let error = $state('');
  let notice = $state('');
  let latest = $state<string>();
  let latestCommit = $state('');
  let history = $state<RepositoryCommit[]>([]);
  let diff = $state('');
  let diffCommit = $state('');
  let preview = $state<RepositoryMergePreview>();
  let mergeTarget = $state('main');
  let mergeSource = $state('');
  let resolutions = $state<
    Record<
      string,
      { text: string; deleted: boolean; confirmed: boolean; binary: boolean; raw: string | null }
    >
  >({});
  let sequence = 0;
  const receipts = new SvelteMap<string, string>();
  const dirty = $derived(
    editing && (content !== original || path !== originalPath || originalPath === ''),
  );
  const language = $derived(
    path.endsWith('.lean')
      ? 'LEAN'
      : path.endsWith('.py')
        ? 'PYTHON'
        : path.endsWith('.md')
          ? 'MARKDOWN'
          : path.endsWith('.json')
            ? 'JSON'
            : 'TEXT',
  );
  const agentBranches = $derived(
    Object.keys(repoState?.branches ?? {}).filter((name) => name !== 'main'),
  );
  const lineCount = $derived(content.split('\n').length);
  const changed = $derived(Boolean(base && repoState?.commit && base !== repoState.commit));

  beforeNavigate(({ cancel, to }) => {
    if (onTabsChange) return;
    const destination = to?.url.pathname;
    if (
      children &&
      destination &&
      [`/workspaces/${projectId}`, `/projects/${projectId}`].some(
        (root) => destination === root || destination.startsWith(`${root}/`),
      )
    )
      return;
    if (unsavedCount && !confirm('Leave without saving your file changes?')) cancel();
  });
  function canLeave() {
    return !unsavedCount || confirm('Discard unsaved file changes in all open tabs?');
  }
  function key(body: unknown) {
    const serialized = JSON.stringify(body);
    let value = receipts.get(serialized);
    if (!value) {
      value = crypto.randomUUID();
      receipts.set(serialized, value);
    }
    return value;
  }
  async function refresh() {
    if (!api || busy) return;
    const selectedBranch = branch;
    try {
      const next = await api.state(projectId, selectedBranch);
      if (selectedBranch !== branch) return;
      repoState = next;
      if (base !== next.commit && editing && !dirty && originalPath) {
        if ((next.files ?? []).some((file) => file.path === originalPath))
          await open(originalPath, false);
        else {
          tabs = tabs.filter((tab) => tab.id !== activeId);
          activeId = '';
          editing = false;
          notice = 'The selected file was removed by another collaborator.';
        }
      }
    } catch (cause) {
      error = explain(cause);
    }
  }
  onMount(() => {
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);
    return () => {
      clearInterval(timer);
      sequence++;
    };
  });
  async function open(name: string, guard = true) {
    if (!api || !repoState?.commit) return;
    if (guard) {
      const existing = tabs.find((tab) => tab.originalPath === name);
      if (existing) {
        await activate(existing);
        return;
      }
      stash();
    }
    const token = ++sequence;
    const commit = repoState.commit;
    busy = true;
    error = '';
    latest = undefined;
    enhanced = false;
    try {
      const file = await api.file(projectId, commit, name);
      if (token !== sequence || (!guard && dirty)) return;
      binary = false;
      try {
        content = decodeFile(file.content_base64);
        if (content.includes('\0')) binary = true;
      } catch {
        content = '';
        binary = true;
      }
      original = content;
      path = name;
      originalPath = name;
      base = commit;
      editing = true;
      previewText = false;
      renameOpen = false;
      if (guard) {
        activeId = crypto.randomUUID();
        tabs = [
          ...tabs,
          { id: activeId, path, originalPath, content, original, base, binary, enhanced },
        ];
      } else stash();
    } catch (cause) {
      error = explain(cause);
    } finally {
      if (token === sequence) busy = false;
    }
  }
  async function selectBranch(value: string, propagateError = false) {
    if (value === branch) return true;
    if (!api || busy || !canLeave()) return false;
    const token = ++sequence;
    busy = true;
    error = '';
    try {
      const next = await api.state(projectId, value);
      if (token !== sequence || !next.enabled) return false;
      branch = value;
      repoState = next;
      tabs = [];
      activeId = '';
      historyOpen = false;
      editing = false;
      history = [];
      preview = undefined;
      diff = '';
      diffCommit = '';
      return true;
    } catch (cause) {
      error = explain(cause);
      if (propagateError) throw cause;
      return false;
    } finally {
      if (token === sequence) busy = false;
    }
  }
  function create() {
    if (!repoState?.commit) return;
    stash();
    sequence++;
    path = '';
    originalPath = '';
    content = '';
    original = '';
    base = repoState.commit;
    editing = true;
    binary = false;
    enhanced = false;
    latest = undefined;
    renameOpen = true;
    previewText = false;
    activeId = crypto.randomUUID();
    tabs = [
      ...tabs,
      { id: activeId, path, originalPath, content, original, base, binary, enhanced },
    ];
    onFileOpen?.(activeId);
  }
  async function saveChanges(changes: RepositorySave['changes'], expected = base) {
    if (!api) return;
    busy = true;
    error = '';
    notice = '';
    const body: RepositorySave = { branch, expected_commit: expected, changes };
    try {
      const saved = await api.save(projectId, body, key(body));
      receipts.delete(JSON.stringify(body));
      const touched = new Set(changes.map((change) => change.path));
      tabs = tabs.map((tab) =>
        tab.id !== activeId &&
        tab.base === expected &&
        !touched.has(tab.path) &&
        !touched.has(tab.originalPath)
          ? { ...tab, base: saved.commit }
          : tab,
      );
      base = saved.commit;
      original = content;
      originalPath = path;
      renameOpen = false;
      stash();
      latest = undefined;
      notice = 'Saved.';
      busy = false;
      await refresh();
      if (historyOpen) {
        try {
          history = await api.history(projectId, branch);
        } catch (cause) {
          error = `Files saved, but history could not refresh. ${explain(cause)}`;
        }
      }
      return true;
    } catch (cause) {
      error = `${explain(cause)} Your draft is retained.`;
      return false;
    } finally {
      busy = false;
    }
  }
  async function save() {
    const changes: RepositorySave['changes'] = [{ path, content_base64: encodeFile(content) }];
    if (originalPath && path !== originalPath)
      changes.unshift({ path: originalPath, content_base64: null });
    await saveChanges(changes);
  }
  async function remove() {
    if (
      !originalPath ||
      !confirm(`Delete ${originalPath}? Its saved history will remain available.`)
    )
      return;
    if (await saveChanges([{ path: originalPath, content_base64: null }])) {
      const deletedId = activeId;
      tabs = tabs.filter((tab) => tab.id !== deletedId);
      if (tabs[0]) restore(tabs[0]);
      else {
        activeId = '';
        editing = false;
      }
    }
  }
  async function compare() {
    const filePath = originalPath || path;
    if (!api || !filePath) return;
    busy = true;
    try {
      const current = await api.state(projectId, branch);
      repoState = current;
      latestCommit = current.commit ?? '';
      latest = (current.files ?? []).some((item) => item.path === filePath)
        ? decodeFile((await api.file(projectId, latestCommit, filePath)).content_base64)
        : '[No saved file at this path]';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function upload(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !repoState?.commit) return;
    onFileOpen?.();
    if (
      tabs.some(
        (tab) =>
          (tab.id === activeId ? path : tab.path) === file.name &&
          (tab.id === activeId ? dirty : dirtyTab(tab)),
      )
    ) {
      error = 'Save or close the draft for this file before uploading a replacement.';
      input.value = '';
      return;
    }
    if (file.size > 700_000) {
      error = 'Choose a file smaller than 700 KB. Use artifact storage for larger files.';
      input.value = '';
      return;
    }
    busy = true;
    error = '';
    try {
      const body: RepositorySave = {
        branch,
        expected_commit: repoState.commit,
        changes: [
          {
            path: file.name,
            content_base64: bytesToBase64(new Uint8Array(await file.arrayBuffer())),
          },
        ],
      };
      await api!.save(projectId, body, key(body));
      receipts.delete(JSON.stringify(body));
      notice = 'File uploaded.';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
      await refresh();
    }
    input.value = '';
  }
  async function download() {
    if (!api || !originalPath || !base) return;
    try {
      const file = await api.file(projectId, base, originalPath);
      const data = Uint8Array.from(atob(file.content_base64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = originalPath.split('/').at(-1) ?? 'file';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      error = explain(cause);
    }
  }
  export async function loadWorkspaceHistory() {
    if (!historyOpen) await showHistory();
  }
  async function showHistory() {
    historyOpen = onOpenView ? true : !historyOpen;
    if (historyOpen) onOpenView?.('history');
    if (!api || !historyOpen) return;
    try {
      history = await api.history(projectId, branch);
    } catch (cause) {
      error = explain(cause);
    }
  }
  async function showDiff(commit: string) {
    if (!api || !repoState?.commit) return;
    try {
      diff = await api.diff(projectId, commit, repoState.commit);
      diffCommit = commit;
    } catch (cause) {
      error = explain(cause);
    }
  }
  function textPreview(value: string | null): string {
    if (value === null) return '[Absent]';
    try {
      const text = decodeFile(value);
      return text.includes('\0') ? '[Binary file]' : text;
    } catch {
      return '[Binary file]';
    }
  }
  async function review(update = false) {
    if (!api || unsavedCount) return;
    mergeTarget = update ? branch : 'main';
    mergeSource = update ? 'main' : branch;
    try {
      preview = await api.preview(projectId, mergeTarget, mergeSource);
      onOpenView?.('merge');
      resolutions = Object.fromEntries(
        preview.conflicts.map((file) => [
          file.path,
          {
            text: file.current_base64 === null ? '' : textPreview(file.current_base64),
            binary: [file.base_base64, file.current_base64, file.incoming_base64].some(
              (value) => textPreview(value) === '[Binary file]',
            ),
            raw: file.current_base64,
            deleted: file.current_base64 === null,
            confirmed: false,
          },
        ]),
      );
    } catch (cause) {
      error = explain(cause);
      preview = undefined;
    }
  }
  async function merge() {
    if (!api || !preview || unsavedCount) return;
    const body: RepositoryMerge = {
      target: mergeTarget,
      source: mergeSource,
      expected_target: preview.target_commit,
      expected_source: preview.source_commit,
      resolutions: preview.conflicts.length
        ? Object.entries(resolutions).map(([name, value]) => ({
            path: name,
            content_base64: value.deleted
              ? null
              : value.binary
                ? value.raw
                : encodeFile(value.text),
          }))
        : null,
    };
    busy = true;
    try {
      await api.merge(projectId, body, key(body));
      receipts.delete(JSON.stringify(body));
      preview = undefined;
      notice = 'Changes merged.';
      onCloseView?.('merge');
      busy = false;
      await refresh();
    } catch (cause) {
      error = `${explain(cause)} Review the latest changes before retrying.`;
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window
  onkeydown={shortcut}
  onbeforeunload={(event) => {
    if (unsavedCount) event.preventDefault();
  }}
/>
{#if repoState?.enabled}
  <input
    class="sr-only"
    type="file"
    aria-label="Upload file"
    bind:this={uploadInput}
    disabled={!repoState.writable || busy}
    onchange={upload}
  />
{/if}
{#if children}
  {@render children(
    editor,
    repoState?.enabled ? navigator : undefined,
    repoState?.enabled ? fileTabs : undefined,
  )}
{:else}
  <div class="standalone-files">
    <div class="standalone-editor">{@render fileTabs()}{@render editor()}</div>
    {@render navigator()}
  </div>
{/if}

{#snippet navigator()}
  {#if repoState?.enabled}
    <div class="explorer" aria-label="Workspace explorer">
      <div class="explorer-heading">
        <label class="copy-picker"
          ><GitBranch size={14} aria-hidden="true" /><span class="sr-only">Working copy</span
          ><select
            value={branch}
            aria-label="Working copy"
            disabled={busy}
            onchange={async (event) => {
              const select = event.currentTarget;
              await selectBranch(select.value);
              select.value = branch;
            }}
          >
            {#each Object.keys(repoState?.branches ?? { main: '' }) as name (name)}<option
                value={name}>{branchLabel(name)}</option
              >{/each}
          </select></label
        >

        <div class="icon-actions">
          <Button
            variant="ghost"
            size="icon-xs"
            title="New file"
            aria-label="New file"
            disabled={!repoState.writable || busy}
            onclick={() => {
              create();
              onFileOpen?.();
            }}><Plus size={15} /></Button
          >
          <Button
            variant="ghost"
            size="icon-xs"
            title="Upload file"
            aria-label="Upload a file"
            disabled={!repoState.writable || busy}
            onclick={() => uploadInput?.click()}><Upload size={14} /></Button
          >
        </div>
      </div>
      {#if !toolsView}<div class="explorer-views" aria-label="Explorer views">
          <button aria-pressed={sidebar === 'files'} onclick={() => (sidebar = 'files')}
            ><FolderOpen size={14} /> Files</button
          >
          <button aria-pressed={sidebar === 'agents'} onclick={() => (sidebar = 'agents')}
            ><GitBranch size={14} /> Working copies <span>{agentBranches.length}</span></button
          >
        </div>
      {/if}
      {#if toolsView === 'explorer' || (!toolsView && sidebar === 'files')}
        <FileExplorer
          paths={(repoState.files ?? []).map((file) => file.path)}
          selected={editing ? originalPath : ''}
          disabled={busy}
          onopen={async (name) => {
            await open(name);
            onFileOpen?.(activeId);
          }}
        />
      {:else}
        <div class="agent-copies">
          <Button variant="outline" size="sm" onclick={showHistory}
            ><History size={14} />History &amp; differences</Button
          >
          {#if branch !== 'main'}
            <Button
              size="sm"
              disabled={!repoState.writable || busy || Boolean(unsavedCount)}
              onclick={() => review()}>Review changes</Button
            >
            <Button
              variant="outline"
              size="sm"
              disabled={!repoState.writable || busy || Boolean(unsavedCount)}
              onclick={() => review(true)}>Update from shared files</Button
            >
          {/if}
          <p>Saved task files. Open a working copy to inspect its files and review changes.</p>
          <button
            class:chosen={branch === 'main'}
            disabled={busy}
            onclick={() => selectBranch('main')}
            ><FolderOpen size={15} /><span
              >Shared workspace<small>The team's saved workspace</small></span
            ></button
          >
          {#each agentBranches as name (name)}<button
              class:chosen={branch === name}
              disabled={busy}
              onclick={() => selectBranch(name)}
              ><GitBranch size={15} /><span
                >{branchLabel(name)}<small>{repoState.branches?.[name]?.slice(0, 8)}</small></span
              ></button
            >{/each}
          {#if !agentBranches.length}<p>
              No task copies yet. Create a task in the left panel to start a working copy.
            </p>{/if}
        </div>
      {/if}
      <div class="explorer-footer">
        {repoState.files?.length ?? 0} files<span>Shared with members</span>
      </div>
    </div>
  {/if}
{/snippet}

{#snippet fileTabs()}
  <div class="tab-strip">
    <div class="editor-tabs" role="tablist" aria-label="Workspace tabs">
      {@render workspaceTab?.()}
      {#each tabs as tab (tab.id)}
        {@const name = tab.id === activeId ? path : tab.path}
        {@const modified = tab.id === activeId ? dirty : dirtyTab(tab)}
        <div class="editor-tab" class:active={active && tab.id === activeId}>
          <button
            role="tab"
            aria-selected={active && tab.id === activeId}
            aria-controls="file-editor"
            id={`file-tab-${tab.id}`}
            disabled={busy}
            title={name || 'Untitled'}
            onclick={() => activate(tab)}
            onkeydown={(event) => {
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                const index = tabs.findIndex((item) => item.id === tab.id);
                const next =
                  tabs[
                    event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? tabs.length - 1
                        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) %
                          tabs.length
                  ];
                if (next) {
                  void activate(next);
                  document.getElementById(`file-tab-${next.id}`)?.focus();
                }
              }
            }}
            ><FileText size={14} aria-hidden="true" /><span>{fileLabel(name)}</span
            >{#if modified}<span class="dirty-dot" aria-label="Unsaved changes"></span>{/if}</button
          >
          <button
            class="close-tab"
            disabled={busy}
            aria-label={`Close ${fileLabel(name)}`}
            onclick={() => closeTab(tab.id)}><X size={12} /></button
          >
        </div>
      {/each}
    </div>
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="History"
      title="History"
      disabled={busy}
      aria-expanded={historyOpen}
      onclick={() => {
        onFileOpen?.();
        void showHistory();
      }}><History size={15} /></Button
    >
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="Create file"
      title="New file"
      disabled={!repoState?.writable || busy}
      onclick={create}><Plus size={14} /></Button
    >
  </div>
{/snippet}

{#snippet editor()}
  <section
    class="workspace-files"
    class:review-surface={view !== 'file'}
    aria-label="Workspace files"
  >
    {#if error}<div class="message error" role="alert">{error}</div>{/if}
    {#if notice}<div class="message notice" role="status">
        <Check size={14} aria-hidden="true" />{notice}
      </div>{/if}
    {#if !repoState}<div class="empty-editor">
        <FolderOpen size={32} />
        <p>Opening workspace files…</p>
        <Button variant="outline" onclick={refresh}>Retry</Button>
      </div>
    {:else if !repoState.enabled}<div class="empty-editor">
        <FolderOpen size={32} />
        <h2>Workspace files are unavailable</h2>
        <p>File storage is not configured for this deployment.</p>
      </div>
    {:else}
      {#if view === 'file'}<div class="editor-column">
          {#if branch !== 'main'}<div class="branch-banner">
              <GitBranch size={15} aria-hidden="true" /><span
                >You're viewing a saved task working copy.</span
              ><Button
                size="sm"
                disabled={!repoState.writable || busy || Boolean(unsavedCount)}
                onclick={() => review()}><GitMerge size={14} />Review changes</Button
              ><Button
                size="sm"
                variant="ghost"
                disabled={!repoState.writable || busy || Boolean(unsavedCount)}
                onclick={() => review(true)}>Update from shared files</Button
              >
            </div>{/if}
          {#if !repoState.writable}<div class="message readonly">
              <LockKeyhole size={14} /><span
                >This working copy is read-only, archived, or has queued or active agent work.</span
              >
            </div>{/if}
          {#if editing}
            <div class="editor-toolbar">
              <div class="breadcrumbs" title={path}>
                {#each (path || 'Untitled').split('/') as part, index (index)}{#if index}<ChevronRight
                      size={12}
                      aria-hidden="true"
                    />{/if}<span>{part}</span>{/each}
              </div>
              <div class="editor-actions">
                {#if /\.(md|markdown)$/.test(path) && !binary}<Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={previewText ? 'Edit Markdown' : 'Preview Markdown'}
                    title={previewText ? 'Edit Markdown' : 'Preview Markdown'}
                    aria-pressed={previewText}
                    onclick={() => (previewText = !previewText)}
                    >{#if previewText}<Code2 size={15} />{:else}<Eye size={15} />{/if}</Button
                  >{/if}
                <Button
                  size="sm"
                  disabled={!repoState.writable || busy || binary || !path || !dirty}
                  onclick={save}><Save size={14} aria-hidden="true" />Save</Button
                >
                <details class="file-menu">
                  <summary aria-label="File actions" title="File actions">•••</summary>
                  <div>
                    <Button
                      variant="ghost"
                      disabled={!repoState.writable || busy || binary}
                      onclick={() => (renameOpen = !renameOpen)}>Rename file</Button
                    >
                    <Button variant="ghost" disabled={busy || !originalPath} onclick={download}
                      ><Download size={14} />Download</Button
                    >
                    {#if !binary}<Button
                        variant="ghost"
                        disabled={busy || !repoState.writable}
                        onclick={() => {
                          enhanced = !enhanced;
                          previewText = false;
                        }}>{enhanced ? 'Use text editor' : 'Use enhanced editor'}</Button
                      >{/if}
                    <Button
                      variant="ghost"
                      disabled={!repoState.writable || busy || !originalPath}
                      onclick={remove}><Trash2 size={14} />Delete file</Button
                    >
                  </div>
                </details>
              </div>
            </div>
            {#if renameOpen}<div class="file-name-form">
                <label for="workspace-file-path">File path</label><Input
                  id="workspace-file-path"
                  aria-label="File path"
                  placeholder="e.g. proofs/Main.lean"
                  bind:value={path}
                  disabled={!repoState.writable || busy || binary}
                /><small>Use / to create folders. Save to apply.</small>
              </div>{/if}
            {#if changed}<div class="stale-banner">
                <div>
                  <strong>Newer changes are available</strong>
                  <p>Shared files changed since you opened this draft.</p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !(originalPath || path)}
                  onclick={compare}>Compare latest saved file</Button
                >
              </div>{/if}
            <div
              class="editor-surface"
              id="file-editor"
              role="tabpanel"
              aria-labelledby={`file-tab-${activeId}`}
            >
              {#if binary}<div class="empty-editor">
                  <FileText size={32} />
                  <h2>Binary file</h2>
                  <p>Download this file to inspect its contents.</p>
                  <Button variant="outline" onclick={download}
                    ><Download size={14} />Download file</Button
                  >
                </div>
              {:else if previewText}<div class="markdown-preview"><Markdown {content} /></div>
              {:else if enhanced && repoState.writable && !busy}{#key `${activeId}:${base}`}<MonacoSourceEditor
                    bind:value={content}
                    {language}
                  />{/key}
              {:else}<div class="source-editor">
                  <div class="line-gutter" aria-hidden="true">
                    {#each [...Array(Math.min(lineCount, 5000)).keys()] as index (index)}<div>
                        {index + 1}
                      </div>{/each}
                  </div>
                  <textarea
                    aria-label="File contents"
                    bind:value={content}
                    disabled={!repoState.writable || busy}
                    spellcheck="false"
                    wrap="off"
                    onscroll={(event) => {
                      const gutter = event.currentTarget.previousElementSibling;
                      if (gutter) gutter.scrollTop = event.currentTarget.scrollTop;
                    }}
                    onkeydown={(event) => {
                      if (event.key === 'Tab' && !event.shiftKey) {
                        event.preventDefault();
                        const target = event.currentTarget;
                        const start = target.selectionStart;
                        content =
                          content.slice(0, start) + '  ' + content.slice(target.selectionEnd);
                        requestAnimationFrame(() => {
                          target.selectionStart = target.selectionEnd = start + 2;
                        });
                      }
                    }}></textarea>
                </div>{/if}
            </div>
            {#if latest !== undefined}<section
                class="compare-panel"
                aria-label="Compare saved version"
              >
                <h2>Latest saved version</h2>
                <pre>{latest}</pre>
                <Button
                  size="sm"
                  disabled={busy}
                  onclick={() => {
                    base = latestCommit;
                    latest = undefined;
                    if (!repoState?.files?.some((file) => file.path === originalPath))
                      originalPath = '';
                  }}>Keep my draft and use this version as its base</Button
                >
              </section>{/if}
          {:else}<div class="empty-editor">
              <div class="empty-symbol"><FolderOpen size={34} strokeWidth={1.4} /></div>
              <h2>Your research, in files</h2>
              <p>Open a file from the explorer, or start with a note, proof, or computation.</p>
              <div class="empty-actions">
                <Button disabled={!repoState.writable || busy} onclick={create}
                  ><Plus size={14} />Create a file</Button
                ><Button
                  variant="outline"
                  disabled={!repoState.writable || busy}
                  onclick={() => uploadInput?.click()}><Upload size={14} />Upload</Button
                >
              </div>
              <div class="shortcut-hint">
                <kbd>⌘ / Ctrl</kbd> + <kbd>S</kbd><span>Save your current file</span>
              </div>
              <p class="privacy-note">
                Working files are shared with workspace members.<br />Saving files does not publish
                research.
              </p>
            </div>{/if}
        </div>
      {/if}
      {#if historyOpen && (view === 'history' || !onOpenView)}<section
          class="history-panel"
          aria-label="File history"
        >
          <header class="panel-heading">
            <h2><History size={15} />History</h2>
            <span>{branchLabel(branch)}</span><Button
              variant="ghost"
              size="icon-sm"
              aria-label="Close history"
              onclick={() => {
                historyOpen = false;
                onCloseView?.('history');
              }}><X size={14} /></Button
            >
          </header>
          <div class="history-body">
            <div class="commit-list">
              {#each history as item (item.commit)}<button
                  aria-current={diffCommit === item.commit ? 'true' : undefined}
                  onclick={() => showDiff(item.commit)}
                  ><strong>{item.message}</strong><span
                    ><code>{item.commit.slice(0, 8)}</code><time
                      >{new Date(item.created_at).toLocaleString()}</time
                    ></span
                  ></button
                >{/each}{#if !history.length}<p>No history loaded yet.</p>{/if}
            </div>
            <div class="history-diff">
              {#if diff}<FileDiff value={diff} />{:else}<p>
                  {diffCommit
                    ? 'No file differences since this version.'
                    : 'Select a saved version to compare it with the current files.'}
                </p>{/if}
            </div>
          </div>
        </section>{/if}
      {#if view === 'merge' && !preview}<p class="message readonly">
          Select a task working copy in Source control to review its changes.
        </p>{/if}
      {#if preview && (view === 'merge' || !onOpenView)}
        <section class="merge-panel" aria-label="Merge review">
          <h2>Review changes</h2>
          <FileDiff value={preview.diff || 'No file differences.'} />
          {#each preview.conflicts as file (file.path)}
            <fieldset>
              <legend>Resolve {file.path}</legend>
              <details>
                <summary>Base</summary>
                <pre>{textPreview(file.base_base64)}</pre>
              </details>
              <details>
                <summary>Incoming</summary>
                <pre>{textPreview(file.incoming_base64)}</pre>
              </details>
              {#if resolutions[file.path].binary}
                <p>Choose the complete file to retain:</p>
                <Button
                  onclick={() => {
                    resolutions[file.path].raw = file.current_base64;
                    resolutions[file.path].deleted = file.current_base64 === null;
                    resolutions[file.path].confirmed = true;
                  }}>Keep current file</Button
                >
                <Button
                  onclick={() => {
                    resolutions[file.path].raw = file.incoming_base64;
                    resolutions[file.path].deleted = file.incoming_base64 === null;
                    resolutions[file.path].confirmed = true;
                  }}>Use incoming file</Button
                >
              {:else}
                <Textarea
                  aria-label={`Resolution for ${file.path}`}
                  bind:value={resolutions[file.path].text}
                />
              {/if}
              <label
                ><input type="checkbox" bind:checked={resolutions[file.path].deleted} /> Delete this file</label
              >
              <label
                ><input type="checkbox" bind:checked={resolutions[file.path].confirmed} /> I have resolved
                this file</label
              >
            </fieldset>
          {/each}
          <Button
            disabled={busy ||
              Boolean(unsavedCount) ||
              Object.values(resolutions).some((value) => !value.confirmed)}
            onclick={merge}>Merge changes</Button
          >
          <Button
            variant="ghost"
            onclick={() => {
              preview = undefined;
              onCloseView?.('merge');
            }}>Close review</Button
          >
        </section>
      {/if}
      <footer class="status-bar">
        <span><GitBranch size={12} />{branchLabel(branch)}</span><span
          >{unsavedCount
            ? `${unsavedCount} unsaved ${unsavedCount === 1 ? 'file' : 'files'}`
            : 'All changes saved'}</span
        ><span class="status-language"
          >{editing
            ? language === 'TEXT'
              ? 'Plain text'
              : language === 'MARKDOWN'
                ? 'Markdown'
                : language === 'PYTHON'
                  ? 'Python'
                  : language === 'LEAN'
                    ? 'Lean'
                    : 'JSON'
            : ''}</span
        >{#if editing && !binary}<span>{lineCount} lines</span><span>UTF-8</span>{/if}
      </footer>
    {/if}
  </section>
{/snippet}

<style>
  .review-surface .history-panel,
  .review-surface .merge-panel {
    flex: 1;
    min-height: 0;
    max-height: none;
    overflow: auto;
  }
  .review-surface .history-body {
    max-height: none;
    height: calc(100% - 40px);
  }
  .workspace-files {
    display: flex;
    flex-direction: column;
    min-width: 0;
    height: 100%;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    background: var(--background);
    color: var(--foreground);
  }
  .icon-actions,
  .editor-actions,
  .copy-picker {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .copy-picker {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .copy-picker {
    flex-direction: row;
    min-width: 0;
    flex: 1;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.3rem 0.55rem;
    font-size: 0.75rem;
  }
  select {
    background: transparent;
    min-width: 0;
    width: 100%;
    border: 0;
    font: inherit;
  }
  .standalone-editor {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  .standalone-files {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    height: 100%;
  }
  .explorer {
    height: 100%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: color-mix(in srgb, var(--research-accent) 3%, var(--background));
    overflow: auto;
  }
  .explorer-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.65rem;
    gap: 0.35rem;
    min-height: 42px;
  }
  .icon-actions {
    gap: 0;
  }
  .icon-actions :global(button) {
    min-height: 24px;
  }
  .editor-surface > :global(.monaco-source-editor) {
    width: 100%;
    min-height: 0;
    border: 0;
  }

  .explorer-views {
    display: flex;
    padding: 0 0.6rem;
    border-bottom: 1px solid var(--border);
    gap: 0.45rem;
  }
  .explorer-views button {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.68rem;
    padding: 0.45rem 0.15rem;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
  }
  .explorer-views button[aria-pressed='true'] {
    border-bottom-color: var(--primary);
    color: var(--primary);
  }
  .explorer-views button span {
    padding: 0 0.25rem;
    background: var(--background);
    border-radius: 4px;
  }
  .explorer-footer {
    margin-top: auto;
    padding: 0.65rem 0.8rem;
    font-size: 0.65rem;
    color: var(--muted-foreground);
    display: flex;
    justify-content: space-between;
    gap: 0.4rem;
    border-top: 1px solid var(--border);
  }
  .editor-column {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  .tab-strip {
    display: flex;
    align-items: center;
    min-height: 39px;
    flex-shrink: 0;
    background: var(--sidebar);
    border-bottom: 1px solid var(--border);
  }
  .editor-tabs {
    display: flex;
    flex: 1;
    overflow-x: auto;
    min-width: 0;
  }
  .editor-tab {
    display: flex;
    align-items: center;
    max-width: 230px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    border-top: 2px solid transparent;
  }
  .editor-tab.active {
    background: var(--background);
    border-top-color: var(--primary);
  }
  .editor-tab button[role='tab'] {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.6rem 0.55rem 0.6rem 0.8rem;
    font-size: 0.75rem;
    min-width: 0;
  }
  .editor-tab button[role='tab'] > span:not(.dirty-dot) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .editor-tab :global(svg) {
    color: var(--muted-foreground);
    flex-shrink: 0;
  }
  .close-tab {
    padding: 0.3rem;
    margin-right: 0.4rem;
    border-radius: 4px;
  }
  .close-tab:hover {
    background: var(--muted);
  }
  .dirty-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--primary);
    flex-shrink: 0;
  }
  .editor-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.45rem 0.8rem;
    border-bottom: 1px solid var(--border);
    gap: 0.5rem;
  }
  .breadcrumbs {
    display: flex;
    gap: 0.2rem;
    align-items: center;
    font-size: 0.72rem;
    color: var(--muted-foreground);
    overflow: hidden;
  }
  .breadcrumbs span {
    white-space: nowrap;
  }
  .breadcrumbs span:last-child {
    color: var(--foreground);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .editor-actions {
    flex-shrink: 0;
    gap: 0.2rem;
  }
  .file-menu {
    margin: 0;
    position: relative;
  }
  .file-menu summary {
    margin: 0;
    list-style: none;
    cursor: pointer;
    padding: 0.2rem 0.45rem;
    border-radius: 4px;
    color: var(--muted-foreground);
  }
  .file-menu summary::-webkit-details-marker {
    display: none;
  }
  .file-menu > div {
    position: absolute;
    top: 100%;
    right: 0;
    z-index: 5;
    background: var(--background);
    padding: 0.35rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--shadow-raised);
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }
  .file-menu :global(button) {
    justify-content: flex-start;
  }
  .file-name-form {
    padding: 0.6rem 0.8rem;
    background: var(--muted);
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
  }
  .file-name-form label {
    font-size: 0.75rem;
    font-weight: 500;
  }
  .file-name-form :global(input) {
    flex: 1;
    min-width: 150px;
  }
  .file-name-form small {
    width: 100%;
    color: var(--muted-foreground);
    font-size: 0.7rem;
  }
  .editor-surface {
    display: flex;
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: auto;
  }
  .source-editor {
    display: flex;
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
  .line-gutter,
  textarea {
    font:
      0.8rem/1.75 ui-monospace,
      SFMono-Regular,
      Consolas,
      monospace;
    padding: 1rem 0;
    tab-size: 2;
  }
  .line-gutter {
    text-align: right;
    min-width: 48px;
    padding-inline: 0.5rem 0.85rem;
    color: var(--muted-foreground);
    background: var(--background);
    overflow: hidden;
    user-select: none;
    max-height: 100%;
  }
  textarea {
    flex: 1;
    min-width: 0;
    width: 100%;
    padding-inline: 0.5rem 1rem;
    resize: none;
    background: transparent;
    border: 0;
    outline: none;
    color: var(--foreground);
  }
  textarea:focus-visible {
    box-shadow: inset 0 0 0 1px var(--border);
  }
  .markdown-preview {
    max-width: 850px;
    width: 100%;
    padding: 1.5rem 2rem;
    margin-inline: auto;
    overflow-wrap: anywhere;
  }
  .empty-editor {
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 2rem 1rem;
    gap: 0.8rem;
    min-height: 0;
  }
  .empty-editor h2 {
    font-size: 1.15rem;
    font-weight: 550;
    margin: 0;
  }
  .empty-editor p {
    color: var(--muted-foreground);
    font-size: 0.8rem;
    line-height: 1.7;
    max-width: 340px;
    margin: 0;
  }
  .empty-symbol {
    color: var(--muted-foreground);
    background: var(--muted);
    padding: 1.25rem;
    border-radius: 20px;
    margin-bottom: 0.4rem;
  }
  .empty-actions {
    display: flex;
    gap: 0.5rem;
    margin: 0.3rem 0;
  }
  .shortcut-hint {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.7rem;
    color: var(--muted-foreground);
    margin-top: 0.8rem;
  }
  .shortcut-hint span {
    margin-left: 0.4rem;
  }
  kbd {
    padding: 0.1rem 0.3rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    font: inherit;
  }
  .empty-editor p.privacy-note {
    font-size: 0.7rem;
    margin-top: 1rem;
  }
  .message {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.55rem 1rem;
    font-size: 0.78rem;
    border-bottom: 1px solid var(--border);
  }
  .error {
    color: var(--danger);
    background: var(--danger-soft);
  }
  .notice {
    color: var(--success);
    background: var(--success-soft);
  }
  .readonly {
    color: var(--muted-foreground);
    background: var(--muted);
  }
  .stale-banner,
  .branch-banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 0.85rem;
    flex-wrap: wrap;
    font-size: 0.75rem;
    background: var(--info-soft);
    border-bottom: 1px solid var(--border);
  }
  .stale-banner strong {
    font-weight: 550;
  }
  .stale-banner p {
    font-size: 0.72rem;
    margin: 0.2rem 0 0;
  }
  .stale-banner > div {
    flex: 1;
  }
  .branch-banner > span {
    flex: 1;
  }
  .agent-copies {
    padding: 0.6rem;
  }
  .agent-copies p {
    font-size: 0.75rem;
    line-height: 1.6;
    color: var(--muted-foreground);
    padding: 0.2rem 0.3rem 0.7rem;
  }
  .agent-copies button {
    display: flex;
    align-items: flex-start;
    width: 100%;
    gap: 0.6rem;
    text-align: left;
    padding: 0.65rem 0.5rem;
    border-radius: 6px;
    font-size: 0.77rem;
  }
  .agent-copies button.chosen {
    background: var(--background);
    box-shadow: 0 0 0 1px var(--border);
  }
  .agent-copies small {
    display: block;
    color: var(--muted-foreground);
    margin-top: 0.25rem;
    font-size: 0.67rem;
  }
  .status-bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
    padding: 0.4rem 0.9rem;
    border-top: 1px solid var(--border);
    font-size: 0.66rem;
    color: var(--muted-foreground);
    background: var(--sidebar);
  }
  .status-bar span {
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }
  .status-language {
    margin-left: auto;
  }
  .history-panel,
  .merge-panel,
  .compare-panel {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
  }
  .panel-heading {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.35rem 0.8rem;
    background: var(--muted);
  }
  .panel-heading h2 {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75rem;
    font-weight: 600;
    margin: 0;
  }
  .panel-heading > span {
    font-size: 0.7rem;
    color: var(--muted-foreground);
    flex: 1;
  }
  .history-body {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    max-height: 260px;
    overflow: auto;
  }
  .commit-list {
    border-right: 1px solid var(--border);
    overflow: auto;
  }
  .commit-list button {
    text-align: left;
    padding: 0.65rem 0.85rem;
    border-bottom: 1px solid var(--border);
    width: 100%;
    display: block;
  }
  .commit-list button:hover {
    background: var(--muted);
  }
  .commit-list strong {
    display: block;
    font-size: 0.75rem;
    font-weight: 500;
  }
  .commit-list span {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    font-size: 0.65rem;
    color: var(--muted-foreground);
    margin-top: 0.3rem;
  }
  .history-diff {
    min-width: 0;
    overflow: auto;
  }
  .history-diff > p,
  .commit-list > p {
    font-size: 0.78rem;
    color: var(--muted-foreground);
    padding: 1rem;
  }
  .compare-panel,
  .merge-panel {
    padding: 1rem;
    max-height: 55vh;
    overflow: auto;
  }
  .compare-panel h2,
  .merge-panel h2 {
    font-size: 0.9rem;
    font-weight: 600;
    margin-bottom: 0.65rem;
  }
  pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font:
      0.75rem/1.7 ui-monospace,
      monospace;
    padding: 0.6rem 0;
    max-height: 220px;
    overflow: auto;
  }
  fieldset {
    margin-block: 0.75rem;
    padding: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  fieldset label {
    display: block;
    font-size: 0.8rem;
    margin-top: 0.45rem;
  }
  button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  @media (max-width: 700px) {
    .history-body {
      grid-template-columns: minmax(0, 1fr);
    }
    .editor-tabs {
      max-width: calc(100vw - 65px);
    }
    .markdown-preview {
      padding: 1rem;
    }
  }
</style>
