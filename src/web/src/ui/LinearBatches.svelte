<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from '../lib/components/ui/button';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { LinearSession } from '../lib/linear-session';
  import type { LinearBatch, LinearCommand, LinearState } from '../lib/linear-api';
  import { bytesToBase64 } from '../lib/repository-api';
  let { projectId, live }: { projectId: string; live: LinearSession } = $props();
  const { agents } = projectContext();
  type Snapshot = { path: string; content_base64: string; binary: boolean; executable: boolean };
  type Change = { file_id: string; base: Snapshot | null; target: Snapshot | null };
  let batches = $state<LinearBatch[]>([]);
  let selected = $state<LinearBatch>();
  let reviewed = $state<LinearState>();
  let edits = $state<
    { change: Change; text: string; path: string; keep: boolean; current: string }[]
  >([]);
  let error = $state('');
  let busy = $state(false);
  const text = (snapshot: Snapshot | null) =>
    snapshot && !snapshot.binary
      ? new TextDecoder().decode(
          Uint8Array.from(atob(snapshot.content_base64), (c) => c.charCodeAt(0)),
        )
      : snapshot
        ? '[Binary file]'
        : '[File absent]';
  async function load() {
    batches = await live.api.batches(projectId);
  }
  async function act(action: () => Promise<unknown>) {
    busy = true;
    error = '';
    try {
      await action();
      await load();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void load().catch(() => {});
    const timer = setInterval(() => void load().catch(() => {}), 5000);
    return () => clearInterval(timer);
  });
  async function review(batch: LinearBatch) {
    await live.flush();
    reviewed = await live.api.state(projectId);
    selected = batch;
    edits = await Promise.all(
      (batch.changes as Change[]).map(async (change) => {
        const file = reviewed!.files.find((f) => f.id === change.file_id);
        const current = file ? await live.api.file(projectId, file.id) : null;
        return {
          change,
          text: change.target?.binary ? '' : text(change.target),
          path: change.target?.path ?? change.base!.path,
          keep: false,
          current: current
            ? text({ ...current, binary: current.document === null })
            : '[File absent]',
        };
      }),
    );
  }
  async function resolve() {
    if (!selected || !reviewed) return;
    const commands: LinearCommand[] = [];
    for (const edit of edits) {
      if (edit.keep) continue;
      const { target, file_id } = edit.change;
      const current = reviewed.files.find((f) => f.id === file_id);
      if (!target) {
        if (current) commands.push({ kind: 'delete', file_id });
        continue;
      }
      const content_base64 = target.binary
        ? target.content_base64
        : bytesToBase64(new TextEncoder().encode(edit.text));
      if (current && current.binary !== target.binary) commands.push({ kind: 'delete', file_id });
      if (!current || current.binary !== target.binary)
        commands.push({
          kind: 'create',
          file_id: crypto.randomUUID(),
          path: edit.path,
          content_base64,
          binary: target.binary,
          executable: target.executable,
        });
      else {
        if (current.path !== edit.path) commands.push({ kind: 'rename', file_id, path: edit.path });
        commands.push(
          { kind: 'replace', file_id, content_base64 },
          { kind: 'mode', file_id, executable: target.executable },
        );
      }
    }
    // Keeping all current files records an explicit resolution without changing their contents.
    await live.api.resolveBatch(projectId, selected.id, reviewed, commands);
    selected = undefined;
  }
  async function reconcile(batch: LinearBatch) {
    if (!batch.run_id) return;
    const run = await agents.getRun(batch.run_id);
    // Opening a draft never queues or pays for a turn.
    location.assign(`/projects/${projectId}/sessions/${run.session_id}?reconcile=${batch.id}`);
  }
</script>

<details>
  <summary>AI file results ({batches.filter((b) => b.status === 'pending').length} pending)</summary
  >
  {#if error}<p role="alert">{error}</p>{/if}
  {#each batches as batch (batch.id)}<div class="batch">
      <span>{batch.status.replace('_', ' ')}</span>
      <Button variant="ghost" disabled={busy} onclick={() => act(() => review(batch))}
        >Review changes</Button
      >
      {#if batch.status === 'pending'}<Button
          variant="ghost"
          disabled={busy || !live.writable}
          onclick={() => act(() => live.api.retryBatch(projectId, batch.id))}>Retry merge</Button
        >{#if batch.run_id}<Button
            variant="ghost"
            disabled={busy}
            onclick={() => act(() => reconcile(batch))}>Reconcile in chat</Button
          >{/if}{/if}
      {#if batch.status === 'applied'}<Button
          variant="ghost"
          disabled={busy || !live.writable}
          onclick={() => {
            if (
              confirm(
                'Revert this AI result while preserving later edits? Conflicts will need review.',
              )
            )
              void act(() => live.api.revertBatch(projectId, batch.id));
          }}>Revert changes</Button
        >{/if}
    </div>{/each}
</details>
{#if selected}<section class="review" aria-label="Review AI changes">
    <h2>Review AI changes</h2>
    <p>
      These changes are private to you until applied. Review the current files and edit the proposed
      result.
    </p>
    {#each selected.conflicts as conflict, index (index)}<p>{conflict}</p>{/each}
    {#each edits as edit (edit.change.file_id)}<fieldset>
        <legend>{edit.path}</legend><label
          ><input type="checkbox" bind:checked={edit.keep} />Keep current file</label
        >
        <details>
          <summary>Original snapshot</summary>
          <pre>{text(edit.change.base)}</pre>
        </details>
        <details open>
          <summary>Current shared file</summary>
          <pre>{edit.current}</pre>
        </details>
        {#if edit.change.target}<label>Result path<input bind:value={edit.path} /></label
          >{#if edit.change.target.binary}<p>Proposed binary replacement</p>{:else}<label
              >Proposed text<textarea bind:value={edit.text}></textarea></label
            >{/if}{:else}<p>Proposed deletion</p>{/if}
      </fieldset>{/each}
    {#if selected.status === 'pending'}<Button
        disabled={busy || !live.writable}
        onclick={() => act(resolve)}>Apply reviewed result</Button
      >{/if}<Button variant="outline" onclick={() => (selected = undefined)}>Close</Button>
  </section>{/if}

<style>
  .batch {
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
  }
  .review {
    position: fixed;
    inset: 5vh 8vw;
    z-index: 60;
    overflow: auto;
    background: var(--background);
    border: 1px solid var(--border);
    padding: 1.5rem;
    box-shadow: 0 10px 40px #0004;
  }
  pre {
    white-space: pre-wrap;
    max-height: 20vh;
    overflow: auto;
  }
  textarea {
    display: block;
    width: 100%;
    min-height: 10rem;
    font-family: monospace;
  }
  fieldset {
    margin: 1rem 0;
    padding: 0.5rem;
    border: 1px solid var(--border);
  }
</style>
