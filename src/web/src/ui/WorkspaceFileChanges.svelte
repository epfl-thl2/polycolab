<script lang="ts">
  import { onMount } from 'svelte';
  import type * as Monaco from 'monaco-editor';
  let {
    original,
    modified,
    language,
    wordWrap = true,
  }: {
    original: string;
    modified: string;
    language: string;
    wordWrap?: boolean;
  } = $props();
  let container: HTMLDivElement;
  let editor = $state.raw<Monaco.editor.IStandaloneDiffEditor>();
  let monaco = $state.raw<typeof Monaco>();
  let loading = $state(true);
  let error = $state('');
  $effect(() => {
    if (!editor) return;
    const models = editor.getModel();
    if (models && monaco) {
      monaco.editor.setModelLanguage(models.original, language);
      monaco.editor.setModelLanguage(models.modified, language);
    }
    if (models?.original.getValue() !== original) models?.original.setValue(original);
    if (models?.modified.getValue() !== modified) models?.modified.setValue(modified);
    editor.updateOptions({ diffWordWrap: wordWrap ? 'on' : 'off' });
  });
  onMount(() => {
    let disposed = false;
    let instance: Monaco.editor.IStandaloneDiffEditor | undefined;
    let before: Monaco.editor.ITextModel | undefined;
    let after: Monaco.editor.ITextModel | undefined;
    let observer: MutationObserver | undefined;
    const media = matchMedia('(prefers-color-scheme: dark)');
    let theme: (() => void) | undefined;
    void import('../lib/monaco-loader')
      .then(({ monacoReady }) => monacoReady)
      .then((engine) => {
        if (disposed) return;
        monaco = engine;
        before = engine.editor.createModel(original, language);
        after = engine.editor.createModel(modified, language);
        instance = engine.editor.createDiffEditor(container, {
          readOnly: true,
          originalEditable: false,
          renderSideBySide: false,
          automaticLayout: true,
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbersMinChars: 3,
          scrollBeyondLastLine: false,
          diffWordWrap: wordWrap ? 'on' : 'off',
          padding: { top: 0 },
          renderOverviewRuler: false,
        });
        instance.setModel({ original: before, modified: after });
        theme = () => {
          const root = document.documentElement;
          const dark =
            root.classList.contains('dark') ||
            root.dataset.theme === 'dark' ||
            (!root.classList.contains('light') && root.dataset.theme !== 'light' && media.matches);
          engine.editor.setTheme(dark ? 'vs-dark' : 'vs');
        };
        theme();
        media.addEventListener('change', theme);
        observer = new MutationObserver(theme);
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['class', 'data-theme'],
        });
        editor = instance;
        loading = false;
      })
      .catch(() => {
        if (!disposed) {
          error = 'Could not load the changes viewer. Return to Edit to continue working.';
          loading = false;
        }
      });
    return () => {
      disposed = true;
      observer?.disconnect();
      if (theme) media.removeEventListener('change', theme);
      instance?.dispose();
      before?.dispose();
      after?.dispose();
    };
  });
</script>

<div class="changes-surface">
  <div class="changes-caption">HEAD → Current file · includes unsaved edits</div>
  {#if loading}<p role="status">Loading changes…</p>{/if}
  {#if error}<p role="alert">{error}</p>{/if}
  <div bind:this={container} class="changes-editor" aria-label="Changes from HEAD"></div>
</div>

<style>
  .changes-surface {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
  }
  .changes-caption {
    padding: 4px 12px;
    border-bottom: 1px solid var(--border);
    color: var(--muted-foreground);
    font-size: 10px;
  }
  .changes-editor {
    flex: 1;
    min-height: 0;
    width: 100%;
  }
  p {
    font-size: 12px;
    padding: 8px 12px;
    color: var(--muted-foreground);
  }
</style>
