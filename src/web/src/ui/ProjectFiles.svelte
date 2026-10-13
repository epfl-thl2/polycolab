<script lang="ts">
  import { onMount, onDestroy, tick, untrack, type Snippet } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { ProjectEditorSessions } from '../lib/project-editor-session';
  import { createExplorerView, type ExplorerViewState } from '../lib/file-explorer';
  import { beforeNavigate } from '$app/navigation';
  import { projectContext, explain } from '../svelte-lib/context';
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
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import * as Tooltip from '../lib/components/ui/tooltip';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import MonacoSourceEditor from './MonacoSourceEditor.svelte';
  import ProjectEditorHeader from './ProjectEditorHeader.svelte';
  import ProjectFileChanges from './ProjectFileChanges.svelte';
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
    Download,
    Check,
    LockKeyhole,
    GitMerge,
    Ellipsis,
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
    preview?: boolean;
  };
  let tabs = $state<OpenFile[]>([]);
  let activeId = $state('');
  let sidebar = $state<'files' | 'agents'>('files');
  const explorerViews = new SvelteMap<string, ExplorerViewState>();
  let explorerView = $state<ExplorerViewState>(createExplorerView());
  const editorSessions = new ProjectEditorSessions();
  const editorKey = (id: string, selectedBranch = branch) =>
    `${projectId}/${encodeURIComponent(selectedBranch)}/${id}`;
  const currentEditorKey = $derived(editorKey(activeId));
  let loadingFile = $state(false);
  let pendingOpen: { name: string; permanent: boolean; token: number } | undefined;
  export function cancelProjectFileLoad() {
    if (!loadingFile) return;
    sequence++;
    pendingOpen = undefined;
    loadingFile = false;
    busy = false;
  }
  onDestroy(() => {
    sequence++;
    editorSessions.dispose();
  });
  export function pinProjectFile(id: string) {
    if (!tabs.some((tab) => tab.id === id && tab.preview)) return;
    tabs = tabs.map((tab) => (tab.id === id && tab.preview ? { ...tab, preview: false } : tab));
  }
  function retainPlainView(node: HTMLTextAreaElement, key: string) {
    const entry = editorSessions.entry(key);
    let alive = true;
    const restoreView = () => {
      if (!alive || !entry.plain) return;
      const saved = entry.plain;
      node.setSelectionRange(saved.start, saved.end, saved.direction);
      node.scrollTop = saved.top;
      node.scrollLeft = saved.left;
      if (node.previousElementSibling) node.previousElementSibling.scrollTop = saved.top;
    };
    void tick().then(restoreView);
    return {
      destroy() {
        alive = false;
        entry.plain = {
          start: node.selectionStart,
          end: node.selectionEnd,
          direction: node.selectionDirection,
          top: node.scrollTop,
          left: node.scrollLeft,
        };
      },
    };
  }
  let historyOpen = $state(false);
  let editorMode = $state<'source' | 'preview' | 'changes'>('source');
  let wordWrap = $state(true);
  let headContent = $state('');
  let changesLoading = $state(false);
  let changesError = $state('');
  let changesRetry = $state(0);
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
      ? 'Main'
      : branchLabels[name] || `Working copy · ${name.split('/').at(-1)?.slice(0, 8)}`;
  function stash() {
    if (!activeId || !editing) return;
    tabs = tabs.map((tab) =>
      tab.id === activeId
        ? {
            ...tab,
            path,
            originalPath,
            content,
            original,
            base,
            binary,
            enhanced,
            preview: tab.preview && !dirty,
          }
        : tab,
    );
  }
  function restore(tab: OpenFile) {
    activeId = tab.id;
    ({ path, originalPath, content, original, base, binary, enhanced } = tab);
    editing = true;
    latest = undefined;
    editorMode = 'source';
    renameOpen = !tab.originalPath;
    notice = '';
  }
  async function activate(tab: OpenFile) {
    cancelProjectFileLoad();
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
    cancelProjectFileLoad();
    if (busy) return;
    stash();
    const tab = tabs.find((item) => item.id === id);
    if (!tab || (dirtyTab(tab) && !confirm(`Discard unsaved changes to ${fileLabel(tab.path)}?`)))
      return;
    const index = tabs.findIndex((item) => item.id === id);
    tabs = tabs.filter((item) => item.id !== id);
    editorSessions.release(editorKey(id));
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
    projectTab,
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
    projectTab?: Snippet;
    onFileOpen?: (id?: string) => void;
    toolsView?: 'explorer' | 'source-control';
    view?: 'file' | 'history' | 'merge';
    onTabsChange?: (
      tabs: { id: string; label: string; path: string; dirty: boolean; preview?: boolean }[],
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
      preview: tab.preview && !(tab.id === activeId ? dirty : dirtyTab(tab)),
    }));
    const selected = activeId;
    untrack(() => onTabsChange?.(items, selected));
  });
  $effect(() => {
    if (dirty) untrack(() => pinProjectFile(activeId));
  });
  export function hasUnsavedProjectFiles() {
    return Boolean(
      unsavedCount ||
      [...branchDrafts.entries()].some(
        ([name, saved]) => name !== branch && saved.tabs.some(dirtyTab),
      ),
    );
  }
  export function selectProjectFile(id: string) {
    cancelProjectFileLoad();
    if (busy) return false;
    const tab = tabs.find((item) => item.id === id);
    if (tab) void activate(tab);
    return Boolean(tab);
  }
  export function closeProjectFile(id: string) {
    closeTab(id);
    return !tabs.some((item) => item.id === id);
  }
  export async function openProjectFile(name: string) {
    const id = await open(name);
    if (id) onFileOpen?.(id);
  }
  export async function selectProjectBranch(name: string) {
    return selectBranch(name, true);
  }
  const api = projectContext().repository;
  const branchDrafts = new SvelteMap<string, { tabs: OpenFile[]; activeId: string }>();
  let commitMessage = $state('');
  let commitReview = $state<{ revision: string; diff: string }>();
  let repoState = $state<RepositoryState>();
  const explorerPaths = $derived.by(() => {
    const ignored = new Set(repoState?.ignored_files ?? []);
    return (repoState?.files ?? [])
      .map((file) => file.path)
      .filter(
        (name) =>
          (explorerView.showDotfiles || !name.split('/').some((part) => part.startsWith('.'))) &&
          (explorerView.showIgnoredFiles || !ignored.has(name)),
      );
  });
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
  let enhanced = $state(true);
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
  const headCommit = $derived(repoState?.head_commit);
  const addedFile = $derived(
    !originalPath ||
      Boolean(
        repoState?.changed_files?.some(
          (file) => file.path === originalPath && file.status === 'added',
        ),
      ),
  );
  $effect(() => {
    const name = originalPath;
    const head = headCommit;
    const isNew = addedFile;
    const selected = currentEditorKey;
    const retry = changesRetry;
    if (editorMode !== 'changes' || binary) return;
    // Each request belongs to the selected file and HEAD, including retries.
    void selected;
    void retry;
    let canceled = false;
    changesError = '';
    headContent = '';
    changesLoading = !isNew;
    if (isNew) return;
    if (!api || !head) {
      changesLoading = false;
      changesError = 'The committed version of this file is unavailable.';
      return;
    }
    void api
      .file(projectId, head, name)
      .then((file) => {
        if (canceled) return;
        headContent = decodeFile(file.content_base64);
      })
      .catch((cause) => {
        if (!canceled) changesError = `Could not load the committed file. ${explain(cause)}`;
      })
      .finally(() => {
        if (!canceled) changesLoading = false;
      });
    return () => {
      canceled = true;
    };
  });
  const lineCount = $derived(content.split('\n').length);
  const changed = $derived(Boolean(base && repoState?.commit && base !== repoState.commit));

  beforeNavigate(({ cancel, to }) => {
    if (onTabsChange) return;
    const destination = to?.url.pathname;
    if (
      children &&
      destination &&
      [`/projects/${projectId}`, `/projects/${projectId}`].some(
        (root) => destination === root || destination.startsWith(`${root}/`),
      )
    )
      return;
    if (unsavedCount && !confirm('Leave without saving your file changes?')) cancel();
  });
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
    const version = sequence;
    try {
      const next = await api.state(projectId, selectedBranch);
      if (selectedBranch !== branch || version !== sequence || busy) return;
      repoState = next;
      if (base !== next.commit && editing && !dirty && originalPath) {
        if ((next.files ?? []).some((file) => file.path === originalPath))
          await open(originalPath, false);
        else {
          editorSessions.release(editorKey(activeId));
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
  async function open(name: string, guard = true, mode: 'preview' | 'permanent' = 'permanent') {
    if (!api || !repoState?.commit || (busy && !loadingFile)) return;
    if (pendingOpen?.name === name) {
      if (mode === 'permanent') pendingOpen.permanent = true;
      return;
    }
    if (guard) {
      const existing = tabs.find((tab) => tab.originalPath === name);
      if (existing) {
        cancelProjectFileLoad();
        if (mode === 'permanent') pinProjectFile(existing.id);
        await activate(existing);
        return existing.id;
      }
      stash();
    }
    const token = ++sequence;
    const request = { name, permanent: mode === 'permanent', token };
    pendingOpen = request;
    const commit = repoState.commit;
    const requestedBranch = branch;
    busy = true;
    loadingFile = true;
    error = '';
    try {
      const file = await api.file(projectId, commit, name);
      if (token !== sequence || branch !== requestedBranch || (!guard && dirty)) return;
      let nextContent = '';
      let nextBinary = false;
      try {
        nextContent = decodeFile(file.content_base64);
        nextBinary = nextContent.includes('\0');
      } catch {
        nextBinary = true;
      }
      if (guard) {
        stash();
        const replacement = !request.permanent
          ? tabs.find((tab) => tab.preview && !dirtyTab(tab))
          : undefined;
        const next: OpenFile = {
          id: crypto.randomUUID(),
          path: name,
          originalPath: name,
          content: nextContent,
          original: nextContent,
          base: commit,
          binary: nextBinary,
          enhanced: true,
          preview: !request.permanent,
        };
        tabs = replacement
          ? tabs.map((tab) => (tab.id === replacement.id ? next : tab))
          : [...tabs, next];
        restore(next);
        if (replacement) editorSessions.release(editorKey(replacement.id));
      } else {
        content = nextContent;
        original = nextContent;
        base = commit;
        binary = nextBinary;
        stash();
      }
      latest = undefined;
      return activeId;
    } catch (cause) {
      if (token === sequence) error = explain(cause);
    } finally {
      if (token === sequence) {
        busy = false;
        loadingFile = false;
        pendingOpen = undefined;
      }
    }
  }
  async function openExplorerFile(name: string, mode: 'preview' | 'permanent' = 'preview') {
    const id = await open(name, true, mode);
    if (id) onFileOpen?.(id);
  }
  async function selectBranch(value: string, propagateError = false) {
    if (value === branch) return true;
    if (!api || (busy && !loadingFile)) return false;
    const token = ++sequence;
    loadingFile = false;
    pendingOpen = undefined;
    busy = true;
    error = '';
    try {
      const next = await api.state(projectId, value);
      if (token !== sequence || !next.enabled) return false;
      stash();
      branchDrafts.set(branch, { tabs: [...tabs], activeId });
      explorerViews.set(branch, explorerView);
      explorerView = explorerViews.get(value) || createExplorerView();
      branch = value;
      repoState = next;
      const saved = branchDrafts.get(value);
      tabs = saved?.tabs || [];
      activeId = saved?.activeId || '';
      commitReview = undefined;
      historyOpen = false;
      editing = false;
      history = [];
      preview = undefined;
      diff = '';
      diffCommit = '';
      const selected = tabs.find((tab) => tab.id === activeId);
      if (selected) restore(selected);
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
    enhanced = true;
    latest = undefined;
    renameOpen = true;
    editorMode = 'source';
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
      editorSessions.release(editorKey(deletedId));
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
  export async function loadProjectHistory() {
    if (!historyOpen) await showHistory();
  }
  async function reviewSaved() {
    if (!api || !repoState?.worktree_id || !repoState.commit) return;
    try {
      const revision = repoState.commit;
      commitReview = {
        revision,
        diff: await api.changes(projectId, repoState.worktree_id, revision),
      };
    } catch (cause) {
      error = explain(cause);
    }
  }
  async function commitSaved() {
    if (!api || !repoState?.worktree_id || !commitReview || !commitMessage.trim()) return;
    if (
      unsavedCount &&
      !confirm('Commit only saved changes? Your unsaved editor drafts will remain uncommitted.')
    )
      return;
    busy = true;
    const body = { revision: commitReview.revision, message: commitMessage.trim() };
    try {
      const saved = await api.commit(
        projectId,
        repoState.worktree_id,
        body.revision,
        body.message,
        key(body),
      );
      // Committing changes history, not file contents; these drafts still have the same base.
      tabs = tabs.map((tab) =>
        tab.base === body.revision ? { ...tab, base: saved.revision } : tab,
      );
      if (base === body.revision) base = saved.revision;
      stash();
      commitReview = undefined;
      commitMessage = '';
      notice = 'Saved changes committed.';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
      await refresh();
    }
  }
  async function discardSaved() {
    if (
      !api ||
      !repoState?.worktree_id ||
      !repoState.commit ||
      !confirm(
        'Discard all saved uncommitted changes in this shared worktree? Unsaved editor drafts will be retained.',
      )
    )
      return;
    busy = true;
    const body = { discard: repoState.commit };
    try {
      await api.discard(projectId, repoState.worktree_id, repoState.commit, key(body));
      commitReview = undefined;
      notice = 'Saved changes discarded.';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
      await refresh();
    }
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
      diff = await api.diff(projectId, commit, repoState.head_commit || repoState.commit);
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
      expected_target_revision: preview.target_revision,
      expected_source_revision: preview.source_revision,
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
    if (hasUnsavedProjectFiles()) event.preventDefault();
  }}
/>
{#if repoState?.enabled}
  <input
    class="sr-only"
    type="file"
    aria-label="Upload file"
    bind:this={uploadInput}
    disabled={!repoState?.writable || busy}
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
    <div class="explorer" aria-label="Project explorer">
      <Tooltip.Provider delayDuration={250}>
        <div class="explorer-heading">
          {#if !onTabsChange}
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
          {/if}

          <div class="icon-actions">
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <Button
                    {...props}
                    variant="ghost"
                    size="icon-xs"
                    aria-label="New file"
                    disabled={!repoState?.writable || busy}
                    onclick={() => {
                      create();
                      onFileOpen?.();
                    }}><Plus size={15} /></Button
                  >
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content class="text-[11px] px-2 py-1">New file</Tooltip.Content>
            </Tooltip.Root>
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <Button
                    {...props}
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Upload a file"
                    disabled={!repoState?.writable || busy}
                    onclick={() => uploadInput?.click()}><Upload size={14} /></Button
                  >
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content class="text-[11px] px-2 py-1">Upload file</Tooltip.Content>
            </Tooltip.Root>
          </div>
          <DropdownMenu.Root>
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <DropdownMenu.Trigger
                    {...props}
                    class="explorer-more"
                    aria-label="Explorer more actions"
                    ><Ellipsis size={14} aria-hidden="true" /></DropdownMenu.Trigger
                  >
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content class="text-[11px] px-2 py-1">More actions</Tooltip.Content>
            </Tooltip.Root>
            <DropdownMenu.Content align="end" class="w-40">
              <DropdownMenu.CheckboxItem
                class="explorer-view-option text-[11px] py-1 pl-6 pr-1.5 whitespace-nowrap"
                bind:checked={explorerView.showDotfiles}
              >
                Show Dotfiles
              </DropdownMenu.CheckboxItem>
              <DropdownMenu.CheckboxItem
                class="explorer-view-option text-[11px] py-1 pl-6 pr-1.5 whitespace-nowrap"
                bind:checked={explorerView.showIgnoredFiles}
              >
                Show Git Ignored Files
              </DropdownMenu.CheckboxItem>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </Tooltip.Provider>
      {#if !toolsView}<div class="explorer-views" aria-label="Explorer views">
          <button aria-pressed={sidebar === 'files'} onclick={() => (sidebar = 'files')}
            ><FolderOpen size={14} /> Files</button
          >
          <button aria-pressed={sidebar === 'agents'} onclick={() => (sidebar = 'agents')}
            ><GitBranch size={14} /> Source control
            <span>{repoState.changed_files?.length || 0}</span></button
          >
        </div>
      {/if}
      {#if toolsView === 'explorer' || (!toolsView && sidebar === 'files')}
        <FileExplorer
          paths={explorerPaths}
          hasHiddenFiles={explorerPaths.length < (repoState.files?.length ?? 0)}
          selected={active &&
          view === 'file' &&
          editing &&
          (repoState.files ?? []).some((file) => file.path === originalPath)
            ? originalPath
            : ''}
          bind:viewState={explorerView}
          changes={repoState.changed_files ?? []}
          disabled={busy && !loadingFile}
          onreveal={() => {
            explorerView.showDotfiles ||= originalPath
              .split('/')
              .some((part) => part.startsWith('.'));
            explorerView.showIgnoredFiles ||= (repoState?.ignored_files ?? []).includes(
              originalPath,
            );
          }}
          onopen={openExplorerFile}
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
              onclick={() => review()}>Merge into Main</Button
            >
            <Button
              variant="outline"
              size="sm"
              disabled={!repoState.writable || busy || Boolean(unsavedCount)}
              onclick={() => review(true)}>Update from Main</Button
            >
          {/if}
          <p>
            {repoState.changed_files?.length || 0} saved uncommitted changes{unsavedCount
              ? ` · ${unsavedCount} unsaved drafts`
              : ''}
          </p>
          {#each repoState.changed_files || [] as file (file.path)}<button
              onclick={() => file.status !== 'deleted' && open(file.path)}
              ><span>{file.path}<small>{file.status}</small></span></button
            >{/each}
          <Button
            size="sm"
            disabled={!repoState.writable || busy || !repoState.changed_files?.length}
            onclick={reviewSaved}>Review &amp; commit</Button
          >
          <Button
            size="sm"
            variant="outline"
            disabled={!repoState.writable || busy || !repoState.changed_files?.length}
            onclick={discardSaved}>Discard changes</Button
          >
          {#if commitReview}
            <p>All saved changes in this shared worktree will be committed.</p>
            <pre class="commit-diff">{commitReview.diff}</pre>
            <label
              >Commit message<Input aria-label="Commit message" bind:value={commitMessage} /></label
            >
            <Button
              size="sm"
              disabled={busy || !commitMessage.trim() || commitReview.revision !== repoState.commit}
              onclick={commitSaved}>Commit changes</Button
            >
            {#if commitReview.revision !== repoState.commit}<p>
                Saved files changed. Review again before committing.
              </p>{/if}
          {/if}
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
    <div class="editor-tabs" role="tablist" aria-label="Project tabs">
      {@render projectTab?.()}
      {#each tabs as tab (tab.id)}
        {@const name = tab.id === activeId ? path : tab.path}
        {@const modified = tab.id === activeId ? dirty : dirtyTab(tab)}
        <div
          class="editor-tab"
          class:active={active && tab.id === activeId}
          class:preview={Boolean(tab.preview)}
        >
          <button
            role="tab"
            aria-selected={active && tab.id === activeId}
            aria-controls="file-editor"
            id={`file-tab-${tab.id}`}
            disabled={busy && !loadingFile}
            title={name || 'Untitled'}
            onclick={() => activate(tab)}
            ondblclick={() => pinProjectFile(tab.id)}
            onkeydown={(event) => {
              if (event.key === 'Enter' && tab.preview) {
                event.preventDefault();
                pinProjectFile(tab.id);
                void activate(tab);
              } else if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
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
            disabled={busy && !loadingFile}
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
  <section class="project-files" class:review-surface={view !== 'file'} aria-label="Project files">
    {#if error}<div class="message error" role="alert">{error}</div>{/if}
    {#if notice}<div class="message notice" role="status">
        <Check size={14} aria-hidden="true" />{notice}
      </div>{/if}
    {#if !repoState}<div class="empty-editor">
        <FolderOpen size={32} />
        <p>Opening project files…</p>
        <Button variant="outline" onclick={refresh}>Retry</Button>
      </div>
    {:else if !repoState.enabled}<div class="empty-editor">
        <FolderOpen size={32} />
        <h2>Project files are unavailable</h2>
        <p>File storage is not configured for this deployment.</p>
      </div>
    {:else}
      {#if view === 'file'}<div class="editor-column">
          {#if branch !== 'main'}<div class="branch-banner">
              <GitBranch size={15} aria-hidden="true" /><span>{branchLabel(branch)}</span><Button
                size="sm"
                disabled={!repoState.writable || busy || Boolean(unsavedCount)}
                onclick={() => review()}><GitMerge size={14} />Merge into Main</Button
              ><Button
                size="sm"
                variant="ghost"
                disabled={!repoState.writable || busy || Boolean(unsavedCount)}
                onclick={() => review(true)}>Update from Main</Button
              >
            </div>{/if}
          {#if !repoState.writable}<div class="message readonly">
              <LockKeyhole size={14} /><span
                >This working copy is read-only, archived, or has queued or active agent work.</span
              >
            </div>{/if}
          {#if editing}
            <ProjectEditorHeader
              bind:path
              bind:mode={editorMode}
              bind:renaming={renameOpen}
              bind:wordWrap
              bind:enhanced
              {binary}
              writable={repoState.writable}
              {busy}
              {dirty}
              saved={Boolean(originalPath)}
              onsave={save}
              onrename={() => {
                pinProjectFile(activeId);
                renameOpen = true;
              }}
              ondownload={download}
              ondelete={remove}
              onerror={(message) => (error = message)}
            />
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
              {:else if editorMode === 'changes'}
                {#if changesLoading}<p class="changes-message" role="status">Loading changes…</p>
                {:else if changesError}<div class="changes-message" role="alert">
                    {changesError}<Button variant="ghost" size="sm" onclick={() => changesRetry++}
                      >Retry</Button
                    >
                  </div>
                {:else}{#key currentEditorKey}<ProjectFileChanges
                      original={headContent}
                      modified={content}
                      {wordWrap}
                      language={{
                        LEAN: 'lean4',
                        PYTHON: 'python',
                        TEXT: 'plaintext',
                        MARKDOWN: 'markdown',
                        JSON: 'json',
                      }[language]}
                    />{/key}{/if}
              {:else if editorMode === 'preview'}<div class="markdown-preview">
                  <Markdown {content} />
                </div>
              {:else if enhanced}{#key currentEditorKey}<MonacoSourceEditor
                    bind:value={content}
                    {language}
                    {wordWrap}
                    sessions={editorSessions}
                    sessionKey={currentEditorKey}
                    active={active && view === 'file'}
                    readOnly={!repoState.writable || busy}
                    onEdit={() => pinProjectFile(activeId)}
                    onError={() => {
                      enhanced = false;
                      notice =
                        'The code editor could not load. Your file is available in the text editor.';
                    }}
                  />{/key}
              {:else}{#key currentEditorKey}<div class="source-editor">
                    <div class="line-gutter" class:wrapped={wordWrap} aria-hidden="true">
                      {#each [...Array(Math.min(lineCount, 5000)).keys()] as index (index)}<div>
                          {index + 1}
                        </div>{/each}
                    </div>
                    <textarea
                      use:retainPlainView={currentEditorKey}
                      oninput={() => pinProjectFile(activeId)}
                      aria-label="File contents"
                      bind:value={content}
                      readonly={!repoState?.writable || busy}
                      spellcheck="false"
                      wrap={wordWrap ? 'soft' : 'off'}
                      onscroll={(event) => {
                        const gutter = event.currentTarget.previousElementSibling;
                        if (gutter) gutter.scrollTop = event.currentTarget.scrollTop;
                      }}
                      onkeydown={(event) => {
                        if (
                          event.key === 'Tab' &&
                          !event.shiftKey &&
                          repoState?.writable &&
                          !busy
                        ) {
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
                  </div>{/key}{/if}
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
                <Button disabled={!repoState?.writable || busy} onclick={create}
                  ><Plus size={14} />Create a file</Button
                ><Button
                  variant="outline"
                  disabled={!repoState?.writable || busy}
                  onclick={() => uploadInput?.click()}><Upload size={14} />Upload</Button
                >
              </div>
              <div class="shortcut-hint">
                <kbd>⌘ / Ctrl</kbd> + <kbd>S</kbd><span>Save your current file</span>
              </div>
              <p class="privacy-note">
                Working files are shared with project members.<br />Saving files does not publish
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
          Select a working copy in Source control to review its changes.
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
  .commit-diff {
    max-height: 320px;
    overflow: auto;
    font-size: 11px;
    white-space: pre;
  }
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
  .project-files {
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
    background: var(--sidebar);
    overflow: auto;
  }
  .explorer-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 8px;
    gap: 4px;
    min-height: 28px;
  }
  .icon-actions {
    gap: 0;
  }
  .icon-actions :global(button) {
    min-height: 24px;
  }
  :global(.explorer-more) {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 4px;
    color: var(--muted-foreground);
  }
  :global(.explorer-view-option [data-slot='dropdown-menu-checkbox-item-indicator']) {
    left: 4px;
    right: auto;
  }
  :global(.explorer-more:hover),
  :global(.explorer-more[data-state='open']) {
    background: var(--sidebar-accent);
    color: var(--sidebar-accent-foreground);
  }
  :global(.explorer-more:focus-visible) {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
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
    padding: 6px 8px;
    font-size: 10px;
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
  .editor-tab.preview button[role='tab'] {
    font-style: italic;
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
  .changes-message {
    padding: 12px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .line-gutter.wrapped {
    display: none;
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
    min-width: 36px;
    padding-inline: 4px 8px;
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
    padding: 8px;
    font-size: 11px;
  }
  .agent-copies p {
    font-size: 11px;
    line-height: 1.4;
    color: var(--muted-foreground);
    padding: 0.2rem 0.3rem 0.7rem;
  }
  .agent-copies button {
    display: flex;
    align-items: flex-start;
    width: 100%;
    gap: 0.6rem;
    text-align: left;
    padding: 4px 6px;
    border-radius: 4px;
    font-size: 11px;
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
