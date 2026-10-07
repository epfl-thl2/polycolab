<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { onMount } from 'svelte';
  import type { components } from '@polycolab/api-client';
  import { workspace, explain } from '../svelte-lib/context';
  import ImportedStatement from './ImportedStatement.svelte';
  type Reference = components['schemas']['WorkspaceReferenceRead'];
  let { projectId, canWrite }: { projectId: string; canWrite: boolean } = $props();
  const { records } = workspace();
  let items = $state<Reference[]>([]);
  let cursor = $state<string | null>(null);
  let selected = $state<Reference>();
  let history = $state<Reference[]>([]);
  let historyCursor = $state<string | null>(null);
  let revision = $state('');
  let reason = $state('');
  let error = $state('');
  let busy = $state(false);
  let key = crypto.randomUUID();
  async function load(more = false) {
    busy = true;
    error = '';
    try {
      const page = await records.references(projectId, more ? (cursor ?? undefined) : undefined);
      items = more ? [...items, ...page.items] : page.items;
      cursor = page.next_cursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function inspect(reference: Reference, more = false) {
    busy = true;
    error = '';
    if (selected?.id !== reference.id) {
      history = [];
      revision = '';
      reason = '';
      key = crypto.randomUUID();
    }
    if (selected?.reference_version_id !== reference.reference_version_id)
      key = crypto.randomUUID();
    selected = reference;
    try {
      const page = await records.references(
        projectId,
        more ? (historyCursor ?? undefined) : undefined,
        reference.id,
      );
      history = more ? [...history, ...page.items] : page.items;
      historyCursor = page.next_cursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function upgrade() {
    if (!selected || !canWrite) return;
    busy = true;
    error = '';
    try {
      const updated = await records.upgrade(
        selected.id,
        {
          expected_current_reference_version_id: selected.reference_version_id,
          object_version_id: revision.trim(),
          reason,
        },
        key,
      );
      selected = updated;
      revision = '';
      reason = '';
      key = crypto.randomUUID();
      await load();
      await inspect(updated);
    } catch (cause) {
      error = `${explain(cause)} Your draft is retained. Reload pins and compare the saved version before retrying.`;
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void load();
  });
</script>

<h1>Library imports</h1>
<p>
  Pins refer to exact public versions without copying research. They never follow newer versions
  automatically.
</p>
{#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
<Button type="submit" disabled={busy} onclick={() => load()}>Reload pins</Button>
{#if busy}<LoadingState>Loading…</LoadingState>{/if}
{#each items as reference (reference.id)}
  <article class="panel">
    <h2>{reference.available ? reference.title : 'Source unavailable'}</h2>
    <p>Pin version {reference.number} · <code>{reference.object_version_id}</code></p>
    {#if reference.available}{#key reference.object_version_id}<ImportedStatement
          {reference}
          {canWrite}
        />{/key}{/if}
    {#if reference.available}<a href={`/commons/records/${reference.object_version_id}`}
        >Read exact public version</a
      >{/if}
    <Button type="submit" disabled={busy} onclick={() => inspect(reference)}
      >History and explicit upgrade</Button
    >
  </article>
{:else}<p>
    No Library entries imported yet. <a href="/library">Find a statement or question in Library</a> and
    choose “Copy to workspace” to create an editable research object.
  </p>{/each}
{#if cursor}<Button type="submit" disabled={busy} onclick={() => load(true)}>Load more pins</Button
  >{/if}
{#if selected}
  <section class="panel" aria-label="Reference history and upgrade">
    <h2>Reference history</h2>
    <p>
      Editing base: pin version {selected.number} · <code>{selected.reference_version_id}</code>
    </p>
    <ol>
      {#each history as version (version.reference_version_id)}<li>
          Version {version.number}: {version.available ? version.title : 'Source unavailable'}
          · <code>{version.object_version_id}</code> · {version.reason}
        </li>{/each}
    </ol>
    {#if historyCursor}<Button
        type="submit"
        disabled={busy}
        onclick={() => inspect(selected!, true)}>Load more pin versions</Button
      >{/if}
    {#if canWrite}<form
        onsubmit={(event) => {
          event.preventDefault();
          void upgrade();
        }}
      >
        <h3>Explicitly change the pinned version</h3>
        <p>
          The target must be an accessible public version of this same research object. Earlier pins
          remain in history.
        </p>
        {#if selected.latest_object_version_id && selected.latest_object_version_id !== selected.object_version_id}<p
            class="notice"
          >
            A newer Library version is available. <a
              href={`/library/${selected.object_id}/revisions/${selected.latest_object_version_id}`}
              >Inspect the newer version</a
            > before updating this pin.
          </p>
          <Button
            type="button"
            variant="outline"
            onclick={() => {
              revision = selected!.latest_object_version_id!;
              key = crypto.randomUUID();
            }}>Select latest Library version</Button
          >{/if}
        <Field.Label
          >Target version ID<Input
            required
            bind:value={revision}
            oninput={() => {
              key = crypto.randomUUID();
            }}
          /></Field.Label
        >
        <Field.Label
          >Reason<Textarea
            required
            maxlength={4000}
            bind:value={reason}
            oninput={() => {
              key = crypto.randomUUID();
            }}
          ></Textarea></Field.Label
        >
        <Button type="submit" disabled={busy}>Upgrade from pin version {selected.number}</Button>
      </form>{/if}
  </section>
{/if}
