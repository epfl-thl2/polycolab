<script lang="ts">
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { untrack } from 'svelte';
  import { explain } from '../svelte-lib/context';
  import type { AuthoredSummaryView, DerivedSummaryView } from '../lib/research-structure-view';

  let {
    authored,
    derived,
    canEdit = false,
    defaultSourceRevisionId,
    save,
    history = [],
    hasMoreHistory = false,
    loadingMoreHistory = false,
    loadMoreHistory,
  }: {
    authored?: AuthoredSummaryView;
    derived?: DerivedSummaryView;
    canEdit?: boolean;
    defaultSourceRevisionId?: string;
    save?: (
      content: string,
      sourceRevisionIds: string[],
      baseRevisionId: string | undefined,
      retryKey: string,
    ) => Promise<AuthoredSummaryView>;
    history?: AuthoredSummaryView[];
    hasMoreHistory?: boolean;
    loadingMoreHistory?: boolean;
    loadMoreHistory?: () => void;
  } = $props();

  let content = $state(untrack(() => authored?.content ?? ''));
  let sources = $state(
    untrack(() =>
      (
        authored?.sources.map((source) => source.revisionId) ??
        (defaultSourceRevisionId ? [defaultSourceRevisionId] : [])
      ).join('\n'),
    ),
  );
  let current = $state(untrack(() => authored));
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  let receipt: { body: string; key: string } | undefined;

  async function submit() {
    if (!save) return;
    const sourceRevisionIds = sources
      .split(/[,\n]/)
      .map((value) => value.trim())
      .filter(Boolean);
    const body = JSON.stringify({ content, sourceRevisionIds, base: current?.revisionId });
    receipt = receipt?.body === body ? receipt : { body, key: crypto.randomUUID() };
    busy = true;
    error = '';
    status = '';
    try {
      current = await save(content, sourceRevisionIds, current?.revisionId, receipt.key);
      receipt = undefined;
      status = 'Authored summary saved with exact sources.';
    } catch (cause) {
      error = `${explain(cause)} Your summary and exact source list are retained.`;
    } finally {
      busy = false;
    }
  }
</script>

<section aria-labelledby="research-summaries-heading">
  <h2 id="research-summaries-heading">Research summaries</h2>

  {#if current}
    <article class="panel" aria-labelledby={`authored-summary-${current.revisionId}`}>
      <header>
        <h3 id={`authored-summary-${current.revisionId}`}>Authored summary</h3>
        <strong class="state-label"
          >{current.fresh === null
            ? 'Freshness unavailable'
            : current.fresh
              ? 'Sources current'
              : 'Sources changed'}</strong
        >
      </header>
      <p>{current.content}</p>
      <p class="muted">
        {current.author} · {current.createdAt} · exact summary revision {current.revisionId}
      </p>
      <h4>Exact source versions</h4>
      <ol>
        {#each current.sources as source (source.revisionId)}
          <li><a href={source.href}>{source.title}</a> · version {source.revisionId}</li>
        {:else}
          <li>No sources recorded.</li>
        {/each}
      </ol>
      <p class="muted">Authored summaries are research contributions, not assurance.</p>
    </article>
  {:else}
    <p>No authored summary is visible.</p>
  {/if}

  {#if canEdit && save}
    <form
      class="panel"
      onsubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3>{current ? 'Revise authored summary' : 'Create authored summary'}</h3>
      <Field.Label
        >Summary<Textarea required maxlength={100000} rows={6} bind:value={content}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Exact source version IDs (one per line)<Textarea required rows={4} bind:value={sources}
        ></Textarea></Field.Label
      >
      <p class="muted">
        Source order is preserved. The server validates project access and stale base revisions.
      </p>
      {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
      {#if status}<p role="status">{status}</p>{/if}
      <Button type="submit" disabled={busy}>Save authored summary</Button>
    </form>
  {/if}

  {#if history.length > 0}
    <details>
      <summary>Summary revision history</summary>
      <ol>
        {#each history as revision (revision.revisionId)}
          <li>
            Revision {revision.revisionId} · {revision.author} · {revision.createdAt} ·
            {revision.sources.length} exact source{revision.sources.length === 1 ? '' : 's'}
          </li>
        {/each}
      </ol>
    </details>
  {/if}
  {#if hasMoreHistory}
    <Button
      variant="outline"
      type="button"
      class=""
      disabled={loadingMoreHistory}
      onclick={loadMoreHistory}
    >
      {loadingMoreHistory ? 'Loading summary history…' : 'Load more summary history'}
    </Button>
  {/if}

  {#if derived}
    <article class="panel" aria-labelledby="derived-summary-heading">
      <header>
        <h3 id="derived-summary-heading">Derived summary</h3>
        <strong class="state-label"
          >{derived.fresh === null
            ? 'Freshness unavailable'
            : derived.fresh
              ? 'Index current'
              : 'Rebuild needed'}</strong
        >
      </header>
      <p>{derived.content}</p>
      <p class="muted">
        Rebuildable index output · input digest {derived.inputDigest} · rebuilt {derived.rebuiltAt}
      </p>
      <p class="muted">Derived output does not substitute for authored research or assurance.</p>
    </article>
  {/if}
</section>

<style>
  section,
  article,
  form {
    display: grid;
    gap: 0.75rem;
  }

  article > header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
  }

  h2,
  h3,
  h4,
  p,
  ol {
    margin-top: 0;
  }

  .state-label {
    display: inline-block;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
    font-size: 0.85rem;
  }
</style>
