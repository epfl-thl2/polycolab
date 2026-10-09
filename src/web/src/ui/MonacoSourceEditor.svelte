<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import { onMount } from 'svelte';

  let {
    value = $bindable(),
    language,
  }: {
    value: string;
    language: 'LEAN' | 'PYTHON' | 'TEXT' | 'MARKDOWN' | 'JSON';
  } = $props();
  let container: HTMLDivElement;
  let loading = $state(true);
  let error = $state('');

  onMount(() => {
    let disposed = false;
    let editor: import('monaco-editor').editor.IStandaloneCodeEditor | undefined;
    let subscription: import('monaco-editor').IDisposable | undefined;
    void import('monaco-editor')
      .then((monaco) => {
        if (disposed) return;
        editor = monaco.editor.create(container, {
          value,
          language: {
            LEAN: 'lean4',
            PYTHON: 'python',
            TEXT: 'plaintext',
            MARKDOWN: 'markdown',
            JSON: 'json',
          }[language],
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: 'on',
        });
        subscription = editor.onDidChangeModelContent(() => {
          value = editor?.getValue() ?? value;
        });
        loading = false;
      })
      .catch(() => {
        error = 'The enhanced editor could not be loaded. Return to the accessible text editor.';
        loading = false;
      });
    return () => {
      disposed = true;
      subscription?.dispose();
      editor?.dispose();
    };
  });
</script>

{#if loading}<LoadingState>Loading enhanced source editor…</LoadingState>{/if}
{#if error}<p role="alert">{error}</p>{/if}
<div
  bind:this={container}
  class="monaco-source-editor"
  class:hidden={loading || Boolean(error)}
  aria-label="Enhanced source editor"
></div>

<style>
  .monaco-source-editor {
    min-height: 28rem;
    border: 1px solid var(--demo-line, #c9cecc);
  }

  .hidden {
    display: none;
  }
</style>
