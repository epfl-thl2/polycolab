<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import { onMount, tick, untrack } from 'svelte';
  import { syncEditorModel, type WorkspaceEditorSessions } from '../lib/workspace-editor-session';
  import type * as Monaco from 'monaco-editor';

  let {
    value = $bindable(),
    language,
    sessions,
    sessionKey,
    readOnly = false,
    active = true,
    wordWrap = true,
    onEdit,
    onError,
  }: {
    value: string;
    language: 'LEAN' | 'PYTHON' | 'TEXT' | 'MARKDOWN' | 'JSON';
    sessions?: WorkspaceEditorSessions;
    sessionKey?: string;
    readOnly?: boolean;
    active?: boolean;
    wordWrap?: boolean;
    onEdit?: () => void;
    onError?: () => void;
  } = $props();
  const languageId = $derived(
    { LEAN: 'lean4', PYTHON: 'python', TEXT: 'plaintext', MARKDOWN: 'markdown', JSON: 'json' }[
      language
    ],
  );
  let container: HTMLDivElement;
  let loading = $state(true);
  let error = $state('');
  let editor = $state.raw<Monaco.editor.IStandaloneCodeEditor>();
  let monaco = $state.raw<typeof Monaco>();
  let syncing = false;
  let hiddenView: Monaco.editor.ICodeEditorViewState | null = null;

  $effect(() => {
    const instance = editor;
    const visible = active;
    if (!instance) return;
    let canceled = false;
    untrack(() => {
      if (!visible) hiddenView = instance.saveViewState();
      else
        void tick().then(() => {
          if (canceled) return;
          instance.layout();
          if (hiddenView) instance.restoreViewState(hiddenView);
          hiddenView = null;
        });
    });
    return () => {
      canceled = true;
    };
  });

  $effect(() => {
    if (!editor || !monaco) return;
    editor.updateOptions({ readOnly, wordWrap: wordWrap ? 'on' : 'off' });
    const model = editor.getModel();
    if (!model) return;
    monaco.editor.setModelLanguage(model, languageId);
    const view = editor.saveViewState();
    syncing = true;
    try {
      syncEditorModel(model, value);
    } finally {
      syncing = false;
    }
    if (view) editor.restoreViewState(view);
  });

  onMount(() => {
    let disposed = false;
    let instance: Monaco.editor.IStandaloneCodeEditor | undefined;
    let model: Monaco.editor.ITextModel | undefined;
    let subscription: Monaco.IDisposable | undefined;
    let observer: MutationObserver | undefined;
    const entry = sessionKey ? sessions?.entry(sessionKey) : undefined;
    const media = matchMedia('(prefers-color-scheme: dark)');
    const setTheme = () => {
      const root = document.documentElement;
      const dark =
        root.classList.contains('dark') ||
        root.dataset.theme === 'dark' ||
        (!root.classList.contains('light') && root.dataset.theme !== 'light' && media.matches);
      monaco?.editor.setTheme(dark ? 'vs-dark' : 'vs');
    };
    void import('../lib/monaco-loader')
      .then(({ monacoReady }) => monacoReady)
      .then((engine) => {
        if (disposed) return;
        monaco = engine;
        model =
          sessions && sessionKey
            ? sessions.model(engine, sessionKey, value, languageId)
            : engine.editor.createModel(value, languageId);
        syncEditorModel(model, value);
        instance = engine.editor.create(container, {
          model,
          readOnly,
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: wordWrap ? 'on' : 'off',
          fontSize: 13,
          lineNumbers: 'on',
          lineNumbersMinChars: 3,
          renderLineHighlight: 'line',
          smoothScrolling: true,
          cursorSmoothCaretAnimation: 'off',
          tabSize: 2,
          padding: { top: 0 },
          ariaLabel: 'File contents',
        });
        if (entry?.view) instance.restoreViewState(entry.view);
        subscription = instance.onDidChangeModelContent(() => {
          if (syncing || !instance) return;
          value = instance.getValue();
          onEdit?.();
        });
        editor = instance;
        setTheme();
        observer = new MutationObserver(setTheme);
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['class', 'data-theme'],
        });
        media.addEventListener('change', setTheme);
        loading = false;
      })
      .catch(() => {
        if (disposed) return;
        error = 'The enhanced editor could not be loaded. Return to the accessible text editor.';
        loading = false;
        onError?.();
      });
    return () => {
      disposed = true;
      if (entry && instance) entry.view = hiddenView ?? instance.saveViewState() ?? undefined;
      observer?.disconnect();
      media.removeEventListener('change', setTheme);
      subscription?.dispose();
      instance?.dispose();
      if (!sessions) model?.dispose();
    };
  });
</script>

{#if loading}<LoadingState>Loading enhanced source editor…</LoadingState>{/if}
{#if error}<p role="alert">{error}</p>{/if}
<div
  bind:this={container}
  class="monaco-source-editor"
  class:workspace-editor={Boolean(sessions)}
  class:hidden={loading || Boolean(error)}
  aria-label="Enhanced source editor"
></div>

<style>
  .monaco-source-editor {
    min-height: 28rem;
    border: 1px solid var(--demo-line, #c9cecc);
  }

  .workspace-editor {
    height: 100%;
    min-height: 0;
    border: 0;
  }

  .hidden {
    display: none;
  }
</style>
