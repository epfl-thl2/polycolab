<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Textarea } from '../lib/components/ui/textarea';
  import { untrack } from 'svelte';
  import { explain } from '../svelte-lib/context';
  import type { SourceRevisionDraft, SourceRevisionView } from '../lib/verification-view';

  let {
    source,
    initialDraft,
    save,
    loadCurrent,
    onDraftChange,
  }: {
    source: SourceRevisionView;
    initialDraft?: SourceRevisionDraft;
    save: (draft: SourceRevisionDraft, retryKey: string) => Promise<SourceRevisionView>;
    loadCurrent: () => Promise<SourceRevisionView>;
    onDraftChange?: (draft: SourceRevisionDraft) => void;
  } = $props();

  const restored = untrack(() =>
    initialDraft?.objectId === source.objectId && initialDraft.language === source.language
      ? initialDraft
      : undefined,
  );
  let content = $state(restored?.content ?? untrack(() => source.content));
  let baseRevisionId = $state(restored?.baseRevisionId ?? untrack(() => source.revisionId));
  let savedContent = $state(untrack(() => source.content));
  let savedRevisionId = $state(untrack(() => source.revisionId));
  let savedHref = $state(untrack(() => source.href));
  let latest = $state<SourceRevisionView>();
  let enhanced = $state(false);
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  let receipt: { body: string; key: string } | undefined;
  const dirty = $derived(content !== savedContent || baseRevisionId !== savedRevisionId);
  const draft = $derived({
    objectId: source.objectId,
    baseRevisionId,
    language: source.language,
    content,
  } satisfies SourceRevisionDraft);

  $effect(() => onDraftChange?.(draft));

  function beforeUnload(event: BeforeUnloadEvent) {
    if (dirty) event.preventDefault();
  }

  async function submit() {
    const body = JSON.stringify(draft);
    receipt = receipt?.body === body ? receipt : { body, key: crypto.randomUUID() };
    busy = true;
    error = '';
    status = '';
    try {
      const saved = await save(draft, receipt.key);
      receipt = undefined;
      content = saved.content;
      baseRevisionId = saved.revisionId;
      savedContent = saved.content;
      savedRevisionId = saved.revisionId;
      savedHref = saved.href;
      latest = undefined;
      status = `Source version ${saved.revisionId} saved.`;
    } catch (cause) {
      error = `${explain(cause)} Your source draft is retained.`;
    } finally {
      busy = false;
    }
  }

  async function compare() {
    busy = true;
    try {
      latest = await loadCurrent();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:window onbeforeunload={beforeUnload} />
<section class="panel" aria-labelledby={`source-editor-${source.objectId}`}>
  <header>
    <div>
      <h2 id={`source-editor-${source.objectId}`}>Source editor</h2>
      <p class="muted">Versioned {source.language} source</p>
    </div>
    <Button
      variant="outline"
      type="button"
      class=""
      aria-pressed={enhanced}
      onclick={() => (enhanced = !enhanced)}
    >
      {enhanced ? 'Use accessible text editor' : 'Load enhanced code editor'}
    </Button>
  </header>
  <p class="muted">Exact saved base {baseRevisionId}. Checks run only against saved versions.</p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status} <a href={savedHref}>Open saved version</a></p>{/if}
  <form
    onsubmit={(event) => {
      event.preventDefault();
      void submit();
    }}
  >
    {#if enhanced}
      {#await import('./MonacoSourceEditor.svelte')}<LoadingState
          >Loading editor component…</LoadingState
        >
      {:then module}<module.default bind:value={content} language={source.language} />{/await}
    {:else}
      <Field.Label
        >Source code<Textarea class="editor" required rows={18} bind:value={content}
        ></Textarea></Field.Label
      >
    {/if}
    <Button type="submit" disabled={busy || !dirty}
      >{busy ? 'Saving source…' : 'Save new source version'}</Button
    >
  </form>
  {#if error}<Button
      variant="outline"
      type="button"
      class=""
      disabled={busy}
      onclick={() => void compare()}>Load current source for comparison</Button
    >{/if}
  {#if latest}<section aria-labelledby={`latest-source-${source.objectId}`}>
      <h3 id={`latest-source-${source.objectId}`}>Current saved source {latest.revisionId}</h3>
      <pre><code>{latest.content}</code></pre>
      <p class="muted">Your draft above is unchanged.</p>
      <Button
        type="button"
        onclick={() => {
          baseRevisionId = latest!.revisionId;
          latest = undefined;
          receipt = undefined;
          error = '';
        }}>Use this exact base, retaining my draft</Button
      >
    </section>{/if}
</section>

<style>
  section,
  form {
    display: grid;
    gap: 0.75rem;
  }
  header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
  }
  h2,
  h3,
  p,
  pre {
    margin-top: 0;
  }
  :global(textarea[data-slot='textarea']) {
    min-height: 24rem;
    font-family: ui-monospace, monospace;
  }
  pre {
    max-width: 100%;
    overflow: auto;
    padding: 0.75rem;
    border: 1px solid var(--demo-line, #c9cecc);
  }
  @media (max-width: 520px) {
    header {
      display: grid;
    }
  }
</style>
