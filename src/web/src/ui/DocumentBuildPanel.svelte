<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import {
    latexDiagnostics,
    type DocumentBuild,
    type LatexEngine,
  } from '../lib/document-builds-api';
  import { Button } from '../lib/components/ui/button';
  import PdfPreview from './PdfPreview.svelte';

  let {
    projectId,
    worktreeId,
    revision,
    paths,
    activePath,
    writable,
    dirty,
    saveAll,
    openDiagnostic,
    preferences,
    onPreferences,
  }: {
    projectId: string;
    worktreeId: string;
    revision: string;
    paths: string[];
    activePath: string;
    writable: boolean;
    dirty: boolean;
    preferences?: { mainFile: string; engine: LatexEngine };
    onPreferences: (value: { mainFile: string; engine: LatexEngine }) => void;
    saveAll: () => Promise<string | undefined>;
    openDiagnostic: (path: string, line: number) => Promise<void>;
  } = $props();
  const api = projectContext().documentBuilds;
  let mainFile = $state(untrack(() => preferences?.mainFile ?? ''));
  let engine = $state<LatexEngine>(untrack(() => preferences?.engine ?? 'pdflatex'));
  let builds = $state<DocumentBuild[]>([]);
  let available = $state(false);
  let submitting = $state(false);
  let message = $state('');
  let pdfUrl = $state('');
  let pdfBuild = $state<DocumentBuild>();
  let log = $state('');
  let logId = '';
  let disposed = false;
  let denied = false;
  let refreshing = false;
  let pending: { signature: string; key: string } | undefined;
  const texPaths = $derived(paths.filter((path) => path.toLowerCase().endsWith('.tex')));
  const latest = $derived(builds[0]);
  const running = $derived(
    builds.find((build) => ['preparing', 'queued', 'running'].includes(build.status)),
  );
  const diagnostics = $derived(latexDiagnostics(log, paths));
  const stale = $derived(Boolean(pdfBuild && (pdfBuild.revision !== revision || dirty)));

  $effect(() => {
    if (!mainFile && texPaths.length)
      mainFile = texPaths.includes(activePath) ? activePath : texPaths[0];
  });

  $effect(() => {
    const value = { mainFile, engine };
    untrack(() => onPreferences(value));
  });

  function clearPdf() {
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    pdfUrl = '';
    pdfBuild = undefined;
  }
  function failure(cause: unknown) {
    const status = (cause as { status?: number }).status;
    if (status === 401 || status === 403 || status === 404) {
      denied = true;
      available = false;
      builds = [];
      log = '';
      clearPdf();
    }
    message = explain(cause);
  }
  async function refresh() {
    if (!api || refreshing || denied || disposed) return;
    refreshing = true;
    try {
      const state = await api.list(projectId, worktreeId);
      if (disposed) return;
      builds = state.builds;
      available = state.available;
      const success = builds.find((build) => build.pdf_available);
      if (!success) clearPdf();
      else if (success.id !== pdfBuild?.id) {
        const blob = await api.output(projectId, worktreeId, success.id, 'pdf');
        if (disposed) return;
        clearPdf();
        pdfUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
        pdfBuild = success;
      }
      const current = builds[0];
      if (current?.log_available && current.id !== logId) {
        const blob = await api.output(projectId, worktreeId, current.id, 'log');
        const text = await blob.text();
        if (disposed) return;
        log = text;
        logId = current.id;
      } else if (!current?.log_available) {
        log = '';
        logId = '';
      }
    } catch (cause) {
      if (!disposed) failure(cause);
    } finally {
      refreshing = false;
    }
  }
  async function compile() {
    if (!api || !mainFile) return;
    submitting = true;
    message = '';
    try {
      const saved = await saveAll();
      if (!saved || disposed) return;
      const body = { revision: saved, main_file: mainFile, engine };
      const signature = JSON.stringify(body);
      if (pending?.signature !== signature) pending = { signature, key: crypto.randomUUID() };
      const build = await api.create(projectId, worktreeId, body, pending.key);
      if (disposed) return;
      pending = undefined;
      builds = [build, ...builds.filter((item) => item.id !== build.id)];
      await refresh();
    } catch (cause) {
      if (!disposed) failure(cause);
    } finally {
      submitting = false;
    }
  }
  async function cancel() {
    if (!api || !running) return;
    try {
      await api.cancel(projectId, worktreeId, running.id);
      await refresh();
    } catch (cause) {
      if (!disposed) failure(cause);
    }
  }
  function downloadLog() {
    const url = URL.createObjectURL(new Blob([log], { type: 'text/plain' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'build.log';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  onMount(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  });
  onDestroy(() => {
    disposed = true;
    clearPdf();
  });
</script>

<aside class="build-panel" aria-label="LaTeX compilation">
  <div class="build-controls">
    <label
      >Main document<select
        aria-label="Main LaTeX document"
        bind:value={mainFile}
        disabled={submitting}
      >
        {#each texPaths as path (path)}<option value={path}>{path}</option>{/each}
      </select></label
    >
    <label
      >Compiler<select aria-label="LaTeX engine" bind:value={engine} disabled={submitting}>
        <option value="pdflatex">pdfLaTeX</option><option value="lualatex">LuaLaTeX</option>
      </select></label
    >
    <Button
      size="sm"
      disabled={!available || !writable || !mainFile || Boolean(running) || submitting}
      onclick={compile}
    >
      {submitting ? 'Submitting…' : dirty ? 'Save all & compile' : 'Compile'}
    </Button>
    {#if running && writable}<Button size="sm" variant="outline" onclick={cancel}
        >Cancel build</Button
      >{/if}
  </div>
  {#if !available}<p class="hint">The LaTeX compiler is currently unavailable.</p>{/if}
  {#if message}<p role="alert">{message}</p>{/if}
  {#if latest}<p role="status">
      Build: {latest.status.replace('_', ' ')}{latest.error
        ? ` · ${latest.error.replaceAll('_', ' ')}`
        : ''}
    </p>{/if}
  {#if pdfUrl && pdfBuild}
    <div class="pdf-caption">
      <span>{pdfBuild.main_file} · {pdfBuild.engine}{stale ? ' · Source has changed' : ''}</span>
      <a href={pdfUrl} download="document.pdf">Download PDF</a>
    </div>
    {#key pdfUrl}<PdfPreview url={pdfUrl} />{/key}
    <p class="hint">
      Saved revision {pdfBuild.revision.slice(0, 8)} · Available until {new Date(
        pdfBuild.expires_at,
      ).toLocaleDateString()}
    </p>
  {:else}<p class="empty">Compile a saved LaTeX document to preview its PDF here.</p>{/if}
  {#if diagnostics.length}<ul aria-label="Compilation errors">
      {#each diagnostics as diagnostic, index (`${index}`)}<li>
          <button onclick={() => openDiagnostic(diagnostic.path, diagnostic.line)}
            >{diagnostic.path}:{diagnostic.line} — {diagnostic.message}</button
          >
        </li>{/each}
    </ul>{/if}
  {#if log}<details>
      <summary>Build log</summary><Button size="sm" variant="ghost" onclick={downloadLog}
        >Download log</Button
      >
      <pre>{log}</pre>
    </details>{/if}
</aside>

<style>
  .build-panel {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    min-width: 0;
    min-height: 0;
    overflow: auto;
    padding: 0.8rem;
    border-left: 1px solid var(--border);
    font-size: 0.8rem;
  }
  .build-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: end;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    min-width: 0;
  }
  select {
    max-width: 16rem;
    padding: 0.3rem;
    background: var(--background);
    color: var(--foreground);
    border: 1px solid var(--border);
    border-radius: 0.3rem;
  }
  .hint,
  .empty {
    color: var(--muted-foreground);
  }
  .empty {
    padding: 2rem 0;
  }
  .pdf-caption {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.5rem;
  }

  a,
  li button {
    color: var(--primary);
    text-decoration: underline;
  }
  li button {
    text-align: left;
  }
  pre {
    max-height: 200px;
    overflow: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
