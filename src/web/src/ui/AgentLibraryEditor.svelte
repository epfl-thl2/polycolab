<script lang="ts">
  import { onMount } from 'svelte';
  import { beforeNavigate, goto } from '$app/navigation';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import {
    libraryError,
    type AgentLibraryApi,
    type LibraryContent,
    type LibraryKind,
    type LibraryOwned,
  } from '../lib/agent-library-api';
  import { ApiError } from '../lib/research-api';
  import LoadingState from './LoadingState.svelte';
  import Markdown from './Markdown.svelte';
  let { api, entryId }: { api: AgentLibraryApi; entryId?: string } = $props();
  let owned = $state<LibraryOwned>();
  let kind = $state<LibraryKind>('PROMPT');
  let title = $state('');
  let description = $state('');
  let content = $state('');
  let instructions = $state('');
  let tags = $state('');
  let license = $state('');
  let sourceUrl = $state('');
  let runtime = $state('');
  let sourceReference = $state('');
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  let preview = $state(false);
  let loaded = $state(false);
  let savedBody = $state('');
  let releaseHref = $state('');
  let receipt: { operation: string; body: string; key: string } | undefined;
  const draft = $derived<LibraryContent>({
    title,
    description,
    content: kind === 'PLUGIN' ? '' : content,
    instructions,
    tags: [
      ...new Set(
        tags
          .split(',')
          .map((tag) => tag.trim().toLowerCase())
          .filter(Boolean),
      ),
    ],
    license,
    source_url: sourceUrl,
    runtime: kind === 'PLUGIN' ? runtime : '',
    source_reference: kind === 'PLUGIN' ? sourceReference : '',
  });
  const body = $derived(JSON.stringify({ kind, draft }));
  const dirty = $derived(loaded && body !== savedBody);
  const blocked = $derived(busy || !loaded || Boolean(owned?.entry.archived));
  function retryKey(operation: string, value: unknown) {
    const next = JSON.stringify(value);
    if (receipt?.operation !== operation || receipt.body !== next)
      receipt = { operation, body: next, key: crypto.randomUUID() };
    return receipt.key;
  }
  function populate(value: LibraryOwned) {
    owned = value;
    kind = value.entry.kind;
    const d = value.draft;
    title = d.title;
    description = d.description;
    content = d.content ?? '';
    instructions = d.instructions ?? '';
    tags = d.tags?.join(', ') ?? '';
    license = d.license ?? '';
    sourceUrl = d.source_url ?? '';
    runtime = d.runtime ?? '';
    sourceReference = d.source_reference ?? '';
    savedBody = body;
    loaded = true;
  }
  async function load() {
    const id = entryId ?? owned?.entry.id;
    if (!id) {
      savedBody = body;
      loaded = true;
      return;
    }
    busy = true;
    error = '';
    try {
      populate(await api.draft(id));
      preview = false;
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  function contentKey(value: LibraryContent) {
    return JSON.stringify([
      value.title,
      value.description,
      value.content,
      value.instructions,
      value.tags ?? [],
      value.license,
      value.source_url,
      value.runtime,
      value.source_reference,
    ]);
  }
  async function saveDraft() {
    const sent = body;
    const reviewed = contentKey(draft);
    const result = owned
      ? await api.update(
          owned.entry.id,
          draft,
          owned.entry.revision,
          retryKey('update', { id: owned.entry.id, revision: owned.entry.revision, draft }),
        )
      : await api.create(kind, draft, retryKey('create', { kind, draft }));
    owned = result;
    if (contentKey(result.draft) !== reviewed) {
      preview = false;
      throw new ApiError(409, 'agent_library_stale_revision');
    }
    savedBody = sent;
    return result;
  }
  async function save(publish = false) {
    busy = true;
    error = '';
    message = '';
    try {
      const value = !owned || dirty ? await saveDraft() : owned;
      if (publish) {
        const release = await api.publish(
          value.entry.id,
          value.entry.revision,
          retryKey('publish', { id: value.entry.id, revision: value.entry.revision }),
        );
        releaseHref = `/agents/library/${value.entry.id}/versions/${release.id}`;
        populate(await api.draft(value.entry.id));
        message = `Published version ${release.number}.`;
      } else message = 'Private draft saved.';
      if (!entryId) await goto(`/agents/yours/${value.entry.id}/edit`);
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  async function archive() {
    if (!owned) return;
    busy = true;
    error = '';
    try {
      const result = await api.archive(
        owned.entry.id,
        owned.entry.revision,
        !owned.entry.archived,
        retryKey('archive', {
          id: owned.entry.id,
          revision: owned.entry.revision,
          archived: !owned.entry.archived,
        }),
      );
      populate(result);
      preview = false;
      message = result.entry.archived ? 'Entry archived.' : 'Entry restored.';
    } catch (cause) {
      error = libraryError(cause);
    } finally {
      busy = false;
    }
  }
  async function importSkill(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    try {
      if (file.size > 800_000) throw new Error('large');
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      if (text.length > 200_000) throw new Error('large');
      content = text;
      error = '';
      preview = false;
    } catch {
      error = 'Choose a UTF-8 SKILL.md file of at most 200,000 characters.';
    }
  }
  beforeNavigate((navigation) => {
    if (dirty && !window.confirm('You have unsaved changes. Leave this editor?'))
      navigation.cancel();
  });
  onMount(() => {
    void load();
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  });
</script>

<main id="main" class="page narrow" tabindex="-1">
  <a href="/agents/yours">Back to Yours</a>
  <h1>{entryId ? 'Edit library entry' : 'Contribute to the agent library'}</h1>
  <p>Drafts are private. Publishing makes the previewed content available to everyone.</p>
  {#if busy}<LoadingState>Saving or loading entry…</LoadingState>{/if}
  {#if error}<p role="alert">{error}</p>
    {#if entryId || owned}<Button
        variant="outline"
        disabled={busy}
        onclick={() => {
          if (!dirty || window.confirm('Replace your unsaved inputs with the saved draft?'))
            void load();
        }}>Reload saved draft</Button
      >{/if}{/if}
  {#if message}<p role="status">
      {message}
      {#if releaseHref}<a href={releaseHref}>View published version</a>{/if}
    </p>{/if}
  {#if owned?.entry.hidden}<p role="status">
      A moderator has hidden this entry. New publications remain hidden until a moderator restores
      it.
    </p>{/if}
  {#if owned?.entry.archived}<p role="status">
      This entry is archived. Restore it to continue editing.
    </p>{/if}
  {#if owned?.entry.source_version_id}<p>
      Copied from exact source version: <a
        href={`/agents/library/${owned.source_entry_id}/versions/${owned.entry.source_version_id}`}
        >View original version</a
      >. Preserve its attribution and license.
    </p>{/if}
  {#if loaded}
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <fieldset disabled={blocked}>
        {#if !preview}
          <label
            >Type<NativeSelect bind:value={kind} disabled={Boolean(owned)}
              ><option value="PROMPT">Prompt</option><option value="SKILL">Skill</option><option
                value="PLUGIN">Plugin</option
              ></NativeSelect
            ></label
          >
          <label>Title<Input required maxlength={300} bind:value={title} /></label>
          <label>Description<Textarea required maxlength={2000} bind:value={description} /></label>
          {#if kind === 'SKILL'}<label
              >Import SKILL.md<input
                type="file"
                accept=".md,text/markdown,text/plain"
                onchange={importSkill}
              /></label
            >
            <p>
              One SKILL.md file with name and description in YAML frontmatter. Link supporting files
              through the source URL.
            </p>{/if}
          {#if kind !== 'PLUGIN'}<label
              >{kind === 'SKILL' ? 'SKILL.md content' : 'Prompt text'}<Textarea
                required
                maxlength={200000}
                rows={14}
                bind:value={content}
              /></label
            >{/if}
          {#if kind === 'PLUGIN'}<label
              >Target runtime<Input required maxlength={100} bind:value={runtime} /></label
            ><label
              >Source version/reference<Input maxlength={300} bind:value={sourceReference} /></label
            >{/if}
          <label
            >Source URL<Input
              type="url"
              required={kind === 'PLUGIN'}
              maxlength={2000}
              bind:value={sourceUrl}
            /></label
          >
          <label
            >{kind === 'PLUGIN' ? 'Setup instructions' : 'Usage instructions'}<Textarea
              required={kind === 'PLUGIN'}
              maxlength={20000}
              rows={5}
              bind:value={instructions}
            /></label
          >
          <label>Tags (comma separated)<Input bind:value={tags} /></label>
          <label
            >License<Input
              maxlength={300}
              bind:value={license}
              placeholder="e.g. CC-BY-4.0 or upstream license"
            /></label
          >
          <p>
            A license is required to publish. Only share content you have permission to
            redistribute.
          </p>
        {:else}
          <article class="panel">
            <p>{kind}</p>
            <h2>{title}</h2>
            <p>{description}</p>
            <p>License: {license || 'Required before publication'}</p>
            {#if kind !== 'PLUGIN'}<pre>{content}</pre>{/if}{#if runtime}<p>
                Runtime: {runtime}
              </p>{/if}{#if sourceReference}<p>
                Source reference: {sourceReference}
              </p>{/if}{#if sourceUrl}<p>Source: {sourceUrl}</p>{/if}<Markdown
              content={instructions}
            />
            <p>Tags: {tags}</p>
          </article>
        {/if}
        <div class="actions">
          <Button type="submit">Save draft</Button><Button
            type="button"
            variant="outline"
            onclick={() => (preview = !preview)}
            >{preview ? 'Continue editing' : 'Preview publication'}</Button
          >{#if preview}<Button type="button" onclick={() => save(true)}>Publish</Button>{/if}
        </div>
      </fieldset>
    </form>
    {#if owned}<div class="actions">
        <Button variant="outline" disabled={busy || dirty} onclick={archive}
          >{owned.entry.archived ? 'Restore entry' : 'Archive entry'}</Button
        >{#if owned.entry.published_version_id}<a
            href={`/agents/library/${owned.entry.id}/versions/${owned.entry.published_version_id}`}
            >View published version</a
          >{/if}
      </div>{/if}
  {/if}
</main>

<style>
  main {
    overflow-wrap: anywhere;
  }
  fieldset {
    border: 0;
    padding: 0;
    min-width: 0;
    display: grid;
    gap: 1rem;
  }
  label {
    display: grid;
    gap: 0.4rem;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 1rem 0;
    align-items: center;
  }
  pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
