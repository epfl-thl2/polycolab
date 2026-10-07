<script lang="ts">
  import { NativeSelect } from '../lib/components/ui/native-select';
  import ObjectProgress from './ObjectProgress.svelte';
  import ObjectReviews from './ObjectReviews.svelte';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { page } from '$app/state';
  import { beforeNavigate, goto } from '$app/navigation';
  import { untrack } from 'svelte';
  import { workspace, explain, type Draft } from '../svelte-lib/context';
  import type { ResearchObject, ObjectVersion } from '../lib/research-api';
  import { ApiError } from '../lib/research-api';
  import { editableVersionSnapshot } from '../lib/version-snapshot';
  import Markdown from './Markdown.svelte';
  let {
    projectId,
    objectId,
    canWrite,
    routeUrl,
    onState,
  }: {
    projectId: string;
    objectId: string;
    canWrite: boolean;
    routeUrl?: URL;
    onState?: (state: { label?: string; dirty: boolean }) => void;
  } = $props();
  const { api, query, drafts } = workspace();
  const object = createQuery(
    toStore(() => ({
      queryKey: ['object', projectId, objectId],
      queryFn: () => api.getObject(projectId, objectId),
    })),
  );
  let tab = $state('read');
  $effect(() => {
    const panel = (routeUrl ?? page.url).searchParams.get('panel');
    if (panel && ['history', 'relations', 'discussion', 'reviews'].includes(panel)) tab = panel;
  });
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let latest = $state<ResearchObject>();
  const selectedId = $derived((routeUrl ?? page.url).searchParams.get('revision'));
  const exactVersion = createQuery(
    toStore(() => ({
      queryKey: ['object-version', projectId, objectId, selectedId],
      enabled: Boolean(selectedId),
      queryFn: async () => {
        const value = await api.getVersion(selectedId!);
        if (value.object_id !== objectId) throw new ApiError(404, 'not_found');
        return value;
      },
    })),
  );
  async function showVersion(value?: ObjectVersion) {
    const url = new URL(
      (routeUrl ?? page.url).pathname + (routeUrl ?? page.url).search,
      page.url.origin,
    );
    url.searchParams.delete('panel');
    if (value) {
      query.setQueryData(['object-version', projectId, objectId, value.id], value);
      url.searchParams.set('revision', value.id);
    } else url.searchParams.delete('revision');
    await goto(url, { noScroll: true, keepFocus: true });
  }
  const key = $derived(`${projectId}:${objectId}`);
  let draft = $state<Draft>();
  $effect(() => {
    const data = $object.data;
    if (data && !untrack(() => draft)) {
      draft = drafts.get(key) ?? {
        base: data.current_object_version_id,
        title: data.current_object_version.content.title,
        content: data.current_object_version.content.content_md,
        statementLabel: data.current_object_version.content.statement_label,
        originalStatementLabel: data.current_object_version.content.statement_label,
        proofDirection:
          data.current_object_version.kind === 'PROOF'
            ? (data.current_object_version.content.direction ?? 'SUPPORTS')
            : undefined,
        originalProofDirection:
          data.current_object_version.kind === 'PROOF'
            ? (data.current_object_version.content.direction ?? 'SUPPORTS')
            : undefined,
        originalTitle: data.current_object_version.content.title,
        originalContent: data.current_object_version.content.content_md,
      };
    }
  });
  const dirty = $derived(
    Boolean(
      draft &&
      (draft.title !== draft.originalTitle ||
        draft.content !== draft.originalContent ||
        draft.statementLabel !== draft.originalStatementLabel ||
        draft.proofDirection !== draft.originalProofDirection),
    ),
  );
  $effect(() => {
    onState?.({ label: $object.data?.current_object_version.content.title, dirty });
  });
  $effect(() => {
    if (draft) drafts.set(key, { ...draft });
  });
  beforeNavigate((navigation) => {
    if (routeUrl) return;
    if (
      dirty &&
      navigation.willUnload &&
      !window.confirm('You have unsaved research. Leave this page and discard the draft?')
    )
      navigation.cancel();
  });
  function beforeUnload(event: BeforeUnloadEvent) {
    if (dirty) {
      event.preventDefault();
      event.returnValue = '';
    }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    busy = true;
    error = '';
    notice = '';
    const submitted = { ...draft };
    try {
      const snapshot = editableVersionSnapshot(await api.getVersion(submitted.base));
      if (snapshot.kind === 'STATEMENT')
        snapshot.content.statement_label = submitted.statementLabel ?? 'CLAIM';
      if (snapshot.kind === 'PROOF')
        snapshot.content.direction = submitted.proofDirection ?? 'SUPPORTS';
      snapshot.content.title = submitted.title;
      snapshot.content.content_md = submitted.content;
      const result = await api.createVersion(objectId, {
        expected_current_object_version_id: submitted.base,
        snapshot,
      });
      query.setQueryData(['object', projectId, objectId], result);
      draft = {
        ...draft,
        base: result.current_object_version_id,
        originalTitle: submitted.title,
        originalContent: submitted.content,
        originalStatementLabel: submitted.statementLabel,
        originalProofDirection: submitted.proofDirection,
      };
      latest = undefined;
      await showVersion();
      await query.invalidateQueries({ queryKey: ['objects', projectId] });
      await query.invalidateQueries({ queryKey: ['history', projectId, objectId] });
      notice = `Version ${result.current_object_version.number} saved.`;
    } catch (reason) {
      error = explain(reason);
      if ((reason as { status?: number }).status === 409) {
        try {
          latest = (await api.getObject(projectId, objectId)) as ResearchObject;
        } catch {
          error += ' Latest research could not be loaded. Retry the comparison.';
        }
      }
    } finally {
      busy = false;
    }
  }
  async function compare() {
    try {
      latest = (await api.getObject(projectId, objectId)) as ResearchObject;
    } catch (reason) {
      error = explain(reason);
    }
  }
  const revision = $derived(selectedId ? $exactVersion.data : $object.data?.current_object_version);
</script>

<svelte:window onbeforeunload={beforeUnload} />
{#if $object.isPending || (selectedId && $exactVersion.isPending)}<LoadingState>
    Opening document…
  </LoadingState>{:else if $object.isError || !$object.data}<Alert.Root
    variant="destructive"
    role="alert">{explain($object.error)}</Alert.Root
  >
  <Button type="submit" onclick={() => $object.refetch()}>Retry</Button>
{:else if selectedId && $exactVersion.isError}
  <Alert.Root variant="destructive" role="alert">{explain($exactVersion.error)}</Alert.Root>
  <Button type="button" onclick={() => $exactVersion.refetch()}>Retry exact version</Button>
{:else}
  <article class="document">
    <a href={`/workspaces/${projectId}/research`}>← Research</a>
    <div class="heading mt-6">
      <div>
        <ObjectKindBadge kind={$object.data.kind} />
        <h1>{revision?.content.title}</h1>
        {#if revision?.content.statement_label}<p class="muted">
            {revision.content.statement_label.toLowerCase()}
          </p>{/if}
        {#if revision?.kind === 'PROOF' && revision.content.direction}<p class="muted">
            {revision.content.direction === 'REFUTES' ? 'Refutes' : 'Supports'} its exact statement target
          </p>{/if}
        <p class="muted">
          Version {revision?.number} · {revision?.authorship.actor_kind === 'AGENT'
            ? (revision.authorship.agent_display_name ?? 'Research agent')
            : (revision?.authorship.author_display_name ?? 'Member')} · {revision?.authorship
            .actor_kind === 'AGENT'
            ? 'Agent contribution'
            : 'Human contribution'}
        </p>
      </div>
    </div>
    {#if selectedId}<p class="notice">
        Viewing exact version {revision?.number}.
        <Button type="submit" variant="outline" class="" onclick={() => showVersion()}
          >Return to current version</Button
        >
      </p>{/if}
    <div class="tabs workspace-information-tabs" aria-label="Document views">
      {#each [['read', 'Body'], ['edit', 'Edit'], ['history', 'History'], ['discussion', 'Discussion'], ['progress', 'Progress'], ['reviews', 'Reviews'], ['relations', 'Relationships']] as [id, label] (id)}{#if id !== 'edit' || canWrite}<Button
            type="button"
            variant="ghost"
            aria-label={label}
            aria-pressed={tab === id}
            onclick={() => (tab = id)}>{label}{id === 'edit' && dirty ? ' •' : ''}</Button
          >{/if}{/each}
    </div>
    {#if notice}<p role="status" class="notice">{notice}</p>{/if}
    {#if revision && tab === 'progress'}<ObjectProgress
        version={revision}
        {projectId}
        canWrite={canWrite && !selectedId}
      />{/if}
    {#if tab === 'read'}<Markdown content={revision?.content.content_md ?? ''} />
      <p>
        <a
          href={`/workspaces/${projectId}/records/${revision?.id ?? $object.data.current_object_version_id}`}
          >Read typed record details, outcomes, and exact statement targets</a
        >
      </p>
    {:else if tab === 'reviews' && revision}<ObjectReviews
        versionId={revision.id}
        workspaceId={projectId}
        canReview={canWrite}
      />
    {:else if tab === 'edit' && draft && canWrite}<form onsubmit={save}>
        {#if $object.data.kind === 'STATEMENT'}<Field.Label
            >Statement label<NativeSelect bind:value={draft.statementLabel}
              ><option value="CLAIM">Claim</option><option value="CONJECTURE">Conjecture</option
              ><option value="LEMMA">Lemma</option><option value="PROPOSITION">Proposition</option
              ><option value="THEOREM">Theorem</option><option value="COROLLARY">Corollary</option
              ></NativeSelect
            ></Field.Label
          >{/if}
        {#if $object.data.kind === 'PROOF'}<Field.Label
            >Argument direction<NativeSelect bind:value={draft.proofDirection}
              ><option value="SUPPORTS">Supports</option><option value="REFUTES">Refutes</option
              ></NativeSelect
            ></Field.Label
          >{/if}
        <Field.Label>Title<Input required bind:value={draft.title} /></Field.Label><Field.Label
          >Markdown<Textarea class="editor" required bind:value={draft.content}
          ></Textarea></Field.Label
        >
        <p class="muted">
          Editing from version <code>{draft.base}</code>. {dirty
            ? 'Unsaved changes'
            : 'All changes saved'}
        </p>
        {#if error}<div role="alert" class="notice">
            {error}<Button variant="outline" type="button" class="" onclick={compare}
              >Compare latest version</Button
            >
          </div>{/if}{#if latest}<section class="card">
            <h2>Latest saved version {latest.current_object_version.number}</h2>
            <h3>{latest.current_object_version.content.title}</h3>
            <Markdown content={latest.current_object_version.content.content_md} />
            <p class="muted">
              Your draft remains above. Review the differences before saving against this version.
            </p>
            <Button
              type="button"
              onclick={() => {
                if (draft && latest) {
                  draft.base = latest.current_object_version_id;
                  latest = undefined;
                  error = '';
                  notice = 'Draft retained. Review and save when ready.';
                }
              }}>Use latest version as base, keep my draft</Button
            >
          </section>{/if}<Button type="submit" disabled={busy || !dirty}
          >{busy ? 'Saving…' : 'Save new version'}</Button
        >
      </form>
    {:else if tab === 'history'}{#await import('./History.svelte')}<LoadingState>
          Loading history…
        </LoadingState>{:then module}<module.default
          {projectId}
          {objectId}
          onselect={(value: ObjectVersion) => {
            void showVersion(value);
            tab = 'read';
          }}
        />{/await}
    {:else if tab === 'discussion'}{#await import('./Discussion.svelte')}<LoadingState>
          Loading discussion…
        </LoadingState>{:then module}<module.default
          {objectId}
          revisionId={revision?.id ?? $object.data.current_object_version_id}
          {canWrite}
        />{/await}
    {:else if tab === 'relations'}{#await import('./Relations.svelte')}<LoadingState>
          Loading dependencies…
        </LoadingState>{:then module}<module.default
          {projectId}
          {objectId}
          revisionId={revision?.id ?? $object.data.current_object_version_id}
          {canWrite}
        />{/await}{/if}
  </article>{/if}
