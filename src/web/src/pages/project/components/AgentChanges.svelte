<script lang="ts">
  import FeedbackToast from '../../../ui/FeedbackToast.svelte';
  import { onMount } from 'svelte';
  import { Button } from '../../../lib/components/ui/button';
  import { projectContext, explain } from '../../../svelte-lib/context';
  import type { CollaborativeSession } from '../../../lib/collaborative-session';
  import type {
    ChangeSet,
    CollaborativeCommand,
    CollaborativeState,
  } from '../../../lib/collaborative-api';
  import { bytesToBase64 } from '../../../lib/repository-api';
  let { projectId, live }: { projectId: string; live: CollaborativeSession } = $props();
  const { agents } = projectContext();
  type Snapshot = { path: string; content_base64: string; binary: boolean; executable: boolean };
  type Change = { file_id: string; base: Snapshot | null; target: Snapshot | null };
  let changeSets = $state<ChangeSet[]>([]);
  let selected = $state<ChangeSet>();
  let reviewed = $state<CollaborativeState>();
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
    changeSets = await live.api.changeSets(projectId);
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
  async function review(change_set: ChangeSet) {
    await live.flush();
    reviewed = await live.api.state(projectId);
    selected = change_set;
    edits = await Promise.all(
      (change_set.changes as Change[]).map(async (change) => {
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
    const commands: CollaborativeCommand[] = [];
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
    await live.api.resolveChangeSet(projectId, selected.id, reviewed, commands);
    selected = undefined;
  }
  async function reconcile(change_set: ChangeSet) {
    if (!change_set.run_id) return;
    const run = await agents.getRun(change_set.run_id);
    // Opening a draft never queues or pays for a turn.
    location.assign(
      `/projects/${projectId}/conversations/${run.conversation_id}?reconcile=${change_set.id}`,
    );
  }
</script>

<FeedbackToast pending={busy} message={error} variant={error ? 'error' : 'success'} />

<details>
  <summary
    >Agent file changes ({changeSets.filter((b) => b.status === 'pending').length} to review)</summary
  >
  <p>
    Review changes made by your agents. Conflicting changes wait here for your decision; applied
    changes can be reverted.
  </p>
  {#if !changeSets.length}<p>No agent file changes yet.</p>{/if}
  {#each changeSets as change_set (change_set.id)}<div class="change_set">
      <span>{change_set.status.replace('_', ' ')}</span>
      <Button variant="ghost" disabled={busy} onclick={() => act(() => review(change_set))}
        >Review changes</Button
      >
      {#if change_set.status === 'pending'}<Button
          variant="ghost"
          disabled={busy || !live.writable}
          onclick={() => act(() => live.api.retryChangeSet(projectId, change_set.id))}
          >Retry merge</Button
        >{#if change_set.run_id}<Button
            variant="ghost"
            disabled={busy}
            onclick={() => act(() => reconcile(change_set))}>Reconcile in chat</Button
          >{/if}{/if}
      {#if change_set.status === 'applied'}<Button
          variant="ghost"
          disabled={busy || !live.writable}
          onclick={() => {
            if (
              confirm(
                'Revert this AI result while preserving later edits? Conflicts will need review.',
              )
            )
              void act(() => live.api.revertChangeSet(projectId, change_set.id));
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
  .change_set {
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
