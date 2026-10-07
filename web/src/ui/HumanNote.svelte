<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { untrack } from 'svelte';
  import { explain } from '../svelte-lib/context';
  import type {
    HumanNoteDraft,
    HumanNoteRevisionView,
    HumanNoteView,
  } from '../lib/research-structure-view';

  let {
    objectId,
    objectTitle,
    note,
    canEdit = false,
    save,
    loadCurrent,
    hasMoreHistory = false,
    loadingMoreHistory = false,
    loadMoreHistory,
  }: {
    objectId: string;
    objectTitle: string;
    note?: HumanNoteView;
    canEdit?: boolean;
    save?: (draft: HumanNoteDraft, retryKey: string) => Promise<HumanNoteRevisionView | void>;
    loadCurrent?: () => Promise<HumanNoteRevisionView>;
    hasMoreHistory?: boolean;
    loadingMoreHistory?: boolean;
    loadMoreHistory?: () => void;
  } = $props();

  let content = $state(untrack(() => note?.current.content ?? ''));
  let baseRevisionId = $state(untrack(() => note?.current.revisionId));
  let comparison = $state<HumanNoteRevisionView>();
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  let receipt: { body: string; key: string } | undefined;

  function receiptFor(body: string) {
    receipt = receipt?.body === body ? receipt : { body, key: crypto.randomUUID() };
    return receipt;
  }

  async function submit() {
    if (!save) return;
    const draft = { objectId, baseRevisionId, content };
    const retry = receiptFor(JSON.stringify(draft));
    busy = true;
    error = '';
    status = '';
    try {
      const saved = await save(draft, retry.key);
      if (saved) {
        baseRevisionId = saved.revisionId;
        content = saved.content;
      }
      receipt = undefined;
      comparison = undefined;
      status = 'Private human note saved.';
    } catch (cause) {
      const stale =
        typeof cause === 'object' && cause !== null && 'status' in cause && cause.status === 409;
      error = `${explain(cause)} Your private note draft is retained.${
        stale ? ' Load the current saved note and compare before retrying.' : ''
      }`;
    } finally {
      busy = false;
    }
  }

  async function compare() {
    if (!loadCurrent) return;
    busy = true;
    try {
      comparison = await loadCurrent();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel" aria-labelledby={`human-note-${objectId}`}>
  <h2 id={`human-note-${objectId}`}>Private human note</h2>
  <p>
    Dedicated context for {objectTitle}. It is owned by one human, cannot be edited by agents or
    other humans, and is never publishable.
  </p>

  {#if note}
    <p class="muted">Owner: {note.owner} · current revision {note.current.revisionId}</p>
  {:else}
    <p>No dedicated human note has been created.</p>
  {/if}

  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status}</p>{/if}

  {#if canEdit && save}
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <Field.Label>
        Private note
        <Textarea required maxlength={100000} rows={8} bind:value={content}></Textarea>
      </Field.Label>
      <p class="muted">
        {baseRevisionId
          ? `Editing exact base ${baseRevisionId}.`
          : 'Creating the first note revision.'}
      </p>
      <Button type="submit" disabled={busy}>Save private note</Button>
    </form>
  {:else if note}
    <p>{note.current.content}</p>
    <p class="state-label">Only {note.owner} can revise this note.</p>
  {/if}

  {#if error && loadCurrent}
    <Button variant="outline" type="button" class="" disabled={busy} onclick={() => void compare()}>
      Load current saved note for comparison
    </Button>
  {/if}

  {#if comparison}
    <section aria-labelledby={`note-comparison-${objectId}`}>
      <h3 id={`note-comparison-${objectId}`}>Current saved note</h3>
      <p>{comparison.content}</p>
      <p class="muted">Revision {comparison.revisionId}; your draft above is unchanged.</p>
      <Button
        variant="outline"
        type="button"
        class=""
        onclick={() => {
          baseRevisionId = comparison?.revisionId;
          receipt = undefined;
          error = '';
        }}>Use this exact base, retaining my draft</Button
      >
    </section>
  {/if}

  {#if note && note.history.length > 0}
    <details>
      <summary>Note revision history</summary>
      <ol>
        {#each note.history as revision (revision.revisionId)}
          <li>
            Revision {revision.revisionId} · {revision.author} · {revision.createdAt}
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
      {loadingMoreHistory ? 'Loading note history…' : 'Load more note history'}
    </Button>
  {/if}
</section>

<style>
  section,
  form {
    display: grid;
    gap: 0.75rem;
  }

  h2,
  h3,
  p,
  ol {
    margin-top: 0;
  }

  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }
</style>
