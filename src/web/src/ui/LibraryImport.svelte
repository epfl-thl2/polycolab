<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import * as Field from '../lib/components/ui/field';
  import * as Dialog from '../lib/components/ui/dialog';
  import { onMount } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { CatalogueEntry } from '../lib/catalogue-api';
  import SignIn from './SignIn.svelte';
  let {
    entry,
    variant = 'default',
    size = 'default',
  }: {
    entry: CatalogueEntry;
    variant?: 'default' | 'outline' | 'ghost';
    size?: 'default' | 'sm';
  } = $props();
  const { api, records, auth } = projectContext();
  let workspaceMode = $state<'linear' | 'git'>('linear');
  let visibility = $state<'PUBLIC' | 'PRIVATE'>('PUBLIC');
  let open = $state(false);
  let projects = $state<Awaited<ReturnType<typeof api.listProjects>>['items']>([]);
  let cursor = $state<string>();
  let destination = $state('');
  let name = $state('');
  let busy = $state(false);
  let error = $state('');
  let receipt: { body: string; key: string } | undefined;
  onMount(() => {
    if (
      location.pathname === `/library/${entry.entry_id}/revisions/${entry.object_version.id}` &&
      new URL(location.href).searchParams.get('import') === '1'
    )
      open = true;
  });
  async function load(more = false) {
    busy = true;
    error = '';
    try {
      const page = await api.listProjects(more ? cursor : undefined);
      const writable = page.items.filter(
        (p) => !p.archived_at && ['OWNER', 'CONTRIBUTOR'].includes(p.current_user_role),
      );
      projects = more ? [...projects, ...writable] : writable;
      cursor = page.nextCursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  $effect(() => {
    if (open && auth.signedIn) void load();
  });
  async function copyEntry() {
    busy = true;
    error = '';
    try {
      const body = {
        source_object_version_id: entry.object_version.id,
        ...(destination ? { project_id: destination } : {}),
        project_name: name.trim() || entry.object_version.content.title.slice(0, 200),
        project_visibility: visibility,
        workspace_mode: workspaceMode,
      };
      const serialized = JSON.stringify(body);
      if (receipt?.body !== serialized) receipt = { body: serialized, key: crypto.randomUUID() };
      const copy = await records.copyToProject(body, receipt.key);
      window.location.assign(`/projects/${copy.project_id}/objects/${copy.object_id}`);
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open
  ><Dialog.Trigger
    >{#snippet child({ props })}<Button {...props} {variant} {size}>Copy to project</Button
      >{/snippet}</Dialog.Trigger
  >
  <Dialog.Content class="max-h-[90vh] overflow-y-auto sm:max-w-lg">
    <Dialog.Title>Copy “{entry.object_version.content.title}”</Dialog.Title>
    <Dialog.Description
      >Create an editable copy of this Library version in your project.</Dialog.Description
    >
    {#if !auth.signedIn}<SignIn
        {auth}
        onSignedIn={() =>
          window.location.assign(
            `/library/${entry.entry_id}/revisions/${entry.object_version.id}?import=1`,
          )}
      />{:else}
      <form
        onsubmit={(event) => {
          event.preventDefault();
          void copyEntry();
        }}
      >
        <Field.Label
          >Destination project<NativeSelect bind:value={destination} disabled={busy}>
            <option value="">New project</option>
            {#each projects as project (project.id)}<option value={project.id}
                >{project.name}</option
              >{/each}
          </NativeSelect></Field.Label
        >
        {#if cursor}<Button
            type="button"
            variant="outline"
            disabled={busy}
            onclick={() => load(true)}>Load more projects</Button
          >{/if}
        {#if !destination}<Field.Label
            >Workspace<NativeSelect bind:value={workspaceMode}
              ><option value="linear">Linear history</option><option value="git">Git</option
              ></NativeSelect
            ></Field.Label
          ><Field.Label
            >Project name<Input
              maxlength={200}
              bind:value={name}
              placeholder={entry.object_version.content.title.slice(0, 200)}
            /></Field.Label
          >
          <Field.Label
            >Visibility<NativeSelect bind:value={visibility}>
              <option value="PUBLIC">Public</option><option value="PRIVATE">Private</option>
            </NativeSelect></Field.Label
          >
          <p class="muted">
            {visibility === 'PUBLIC'
              ? 'Anyone can read this project and its saved research.'
              : 'Only project members can read this research.'}
          </p>{/if}
        <p>
          Copying version {entry.object_version.number ?? 1}. Future Library updates will not change
          your copy.
        </p>
        {#if error}<p role="alert">{error}</p>
          <Button type="button" variant="outline" disabled={busy} onclick={() => load()}
            >Reload projects</Button
          >{/if}
        <Button type="submit" disabled={busy}>{busy ? 'Working…' : 'Create copy'}</Button>
      </form>
    {/if}
    <Dialog.Close
      >{#snippet child({ props })}<Button variant="outline" {...props}>Cancel</Button
        >{/snippet}</Dialog.Close
    >
  </Dialog.Content></Dialog.Root
>
