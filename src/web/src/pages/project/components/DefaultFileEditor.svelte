<script lang="ts">
  import { beforeNavigate } from '$app/navigation';
  import { onMount, untrack } from 'svelte';
  import { Button } from '../../../lib/components/ui/button';
  import { projectContext, explain } from '../../../svelte-lib/context';
  import { createDefaultFilesApi, type DefaultFile } from '../../../lib/default-files-api';
  import ProjectFileView from './ProjectFileView.svelte';
  import Markdown from '../../../ui/Markdown.svelte';
  import MonacoSourceEditor from '../../../ui/MonacoSourceEditor.svelte';
  let {
    projectId,
    path,
    writable,
    onChanged,
  }: { projectId: string; path: string; writable: boolean; onChanged: (path?: string) => void } =
    $props();
  const api = createDefaultFilesApi({ getAccessToken: projectContext().auth.token });
  let file = $state<DefaultFile>();
  let text = $state('');
  let rename = $state('');
  let error = $state('');
  let busy = $state(false);
  let enhanced = $state(true);
  let mode = $state<'source' | 'preview' | 'changes'>('source');
  let wordWrap = $state(true);
  const dirty = $derived(Boolean(file && !file.binary && text !== file.content));
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
  let request = 0;
  async function load() {
    const version = ++request;
    const name = path;
    error = '';
    busy = true;
    try {
      const value = await api.command(projectId, { action: 'read', path: name });
      if (version !== request || !('path' in value)) return;
      file = value;
      text = value.content ?? '';
      rename = '';
    } catch (cause) {
      if (version === request) error = explain(cause);
    } finally {
      if (version === request) busy = false;
    }
  }
  $effect(() => {
    void path;
    untrack(() => {
      file = undefined;
      void load();
    });
  });
  export function canClose() {
    if (!dirty && !busy) return true;
    error = 'Save or discard your file edits before opening another file.';
    return false;
  }
  beforeNavigate(({ to, cancel }) => {
    if (dirty || busy) {
      if (
        to?.url.pathname.startsWith(`/projects/${projectId}/`) &&
        (to.url.pathname !== `/projects/${projectId}/files` ||
          to.url.searchParams.get('file') === path)
      )
        return;
      cancel();
      error = 'Save or discard your file edits before leaving.';
    }
  });
  onMount(() => {
    const unload = (event: BeforeUnloadEvent) => {
      if (dirty || busy) event.preventDefault();
    };
    window.addEventListener('beforeunload', unload);
    return () => {
      request++;
      window.removeEventListener('beforeunload', unload);
    };
  });
  async function change(action: 'write' | 'rename' | 'delete') {
    if (!file || busy) return;
    busy = true;
    error = '';
    const contents = text;
    try {
      const value = await api.command(projectId, {
        action,
        path: file.path,
        expected_digest: file.digest,
        ...(action === 'write' ? { content: contents } : {}),
        ...(action === 'rename' ? { destination: rename } : {}),
      });
      if ('path' in value) {
        file = value;
        if (action !== 'write') text = value.content ?? '';
      } else {
        file = undefined;
        text = '';
      }
      busy = false;
      onChanged(
        action === 'rename' && 'path' in value ? value.path : action === 'delete' ? '' : undefined,
      );
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  function download() {
    if (file?.content_base64 == null) return;
    const url = URL.createObjectURL(
      new Blob([Uint8Array.from(atob(file.content_base64), (c) => c.charCodeAt(0))]),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = path.split('/').at(-1)!;
    link.click();
    URL.revokeObjectURL(url);
  }
</script>

<svelte:window
  onkeydown={(event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 's') {
      event.preventDefault();
      if (writable && dirty) void change('write');
    }
  }}
/>
{#if error}<p role="alert">{error}</p>{/if}
{#if !file}<p>{busy ? 'Opening file…' : 'File unavailable.'}</p>
  <Button variant="outline" onclick={load} disabled={busy}>Retry</Button>
{:else}
  <ProjectFileView
    path={file.path}
    bind:mode
    bind:enhanced
    bind:wordWrap
    binary={file.binary}
    {writable}
    {busy}
    {dirty}
    status={busy ? 'Saving…' : dirty ? 'Unsaved changes' : 'Saved'}
    {download}
    onsave={() => {
      void change('write');
    }}
    onrename={(name) => {
      if (dirty) {
        error = 'Save or discard your edits before renaming.';
        return;
      }
      rename = name;
      void change('rename');
    }}
    ondelete={() => {
      if (dirty) {
        error = 'Save or discard your edits before deleting.';
        return;
      }
      if (confirm(`Delete ${file?.path}? This cannot be undone.`)) void change('delete');
    }}
    onerror={(message) => (error = message)}
    onreload={() => {
      if (!dirty || confirm('Discard your unsaved edits?')) void load();
    }}
  >
    {#if file.binary}<p>Binary file. Download it to inspect its contents.</p>
    {:else if mode === 'preview'}<Markdown content={text} />
    {:else if !enhanced}<textarea
        wrap={wordWrap ? 'soft' : 'off'}
        aria-label="File contents"
        bind:value={text}
        disabled={!writable || busy}></textarea>
    {:else}{#key file.path}<MonacoSourceEditor
          bind:value={text}
          {language}
          {wordWrap}
          readOnly={!writable || busy}
          onError={() => (enhanced = false)}
        />{/key}{/if}
  </ProjectFileView>
{/if}
