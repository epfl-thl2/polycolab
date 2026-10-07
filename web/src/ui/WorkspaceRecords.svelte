<script lang="ts">
  import { statementObjectVersionIds, editableVersionSnapshot } from '../lib/version-snapshot';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import { onMount } from 'svelte';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { workspace, explain } from '../svelte-lib/context';
  import type { NewVersionDraft } from '../lib/research-record-draft';
  import type { SourceRevisionDraft, SourceRevisionView } from '../lib/verification-view';
  import {
    proofStructureWrite,
    researchAttemptWrite,
    newVersionSnapshot,
  } from '../lib/research-record-draft';
  import Markdown from './Markdown.svelte';
  import RecordEdit from './RecordEdit.svelte';
  import ProofStructureFields from './ProofStructureFields.svelte';
  let {
    projectId,
    revisionId,
    canWrite,
    canPublish = false,
    publicWorkspace = false,
    publicRead = false,
  }: {
    projectId: string;
    revisionId?: string;
    canWrite: boolean;
    canPublish?: boolean;
    publicWorkspace?: boolean;
    publicRead?: boolean;
  } = $props();
  const { api, records, query, sourceDrafts } = workspace();
  const sourceLanguage = (kind: string): SourceRevisionView['language'] | undefined =>
    kind === 'FORMALIZATION' ? 'LEAN' : kind === 'COMPUTATION' ? 'PYTHON' : undefined;
  const sourceHref = (revision: string) => `/workspaces/${projectId}/records/${revision}`;
  let search = $state('');
  let outcome = $state('');
  let author = $state('');
  let applied = $state({
    q: '',
    status: undefined as string | undefined,
    author: undefined as string | undefined,
  });
  const listing = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['records', projectId, applied],
      enabled: !revisionId,
      initialPageParam: undefined as string | undefined,
      queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
        const page = await (publicRead ? records.publicSearch : records.workspaceSearch)({
          workspace_id: projectId,
          ...applied,
          cursor: pageParam,
        });
        return {
          items: page.items.map((hit) => hit.object_version),
          next_cursor: page.next_cursor,
        };
      },
      getNextPageParam: (page: { next_cursor: string | null }) => page.next_cursor ?? undefined,
    })),
  );
  const selected = createQuery(
    toStore(() => ({
      queryKey: ['record', projectId, revisionId],
      enabled: Boolean(revisionId),
      queryFn: () =>
        publicRead ? records.get(revisionId!) : records.workspaceGet(projectId, revisionId!),
    })),
  );
  let draft = $state<NewVersionDraft>({
    kind: 'NOTE',
    title: '',
    content_md: '',
    assumptions_md: 'None stated',
    reported_outcome: 'UNASSESSED',
    change_summary: '',
  });
  let targets = $state('');
  let conclusionRevisionId = $state('');
  let premiseRevisionIds = $state<string[]>([]);
  let structureProgress = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let attemptTargetRevisionId = $state('');
  let attemptOutcome = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let attemptFindings = $state('');
  let attemptResultRevisionId = $state('');
  let attemptEvidence = $state('');
  let creating = $state(false);
  let busy = $state(false);
  let error = $state('');
  let saved = $state('');
  let receipt: { body: string; key: string } | undefined;
  onMount(() => {
    const params = new URL(location.href).searchParams;
    const target = params.get('import');
    const kind = params.get('kind');
    if (
      canWrite &&
      target &&
      /^[0-9a-f-]{36}$/i.test(target) &&
      (kind === 'ATTEMPT' || kind === 'PROOF' || kind === 'STATEMENT')
    ) {
      draft.kind = kind;
      draft.change_summary = 'Research developed from a Library import';
      targets = target;
      conclusionRevisionId = target;
      attemptTargetRevisionId = target;
      creating = true;
    }
  });
  async function save() {
    if (!canWrite || busy) return;
    busy = true;
    error = '';
    try {
      const body = {
        destination: { kind: 'workspace' as const, workspace_id: projectId },
        snapshot: newVersionSnapshot(
          draft,
          targets.split(/[\s,]+/).filter(Boolean),
          draft.kind === 'PROOF'
            ? proofStructureWrite(conclusionRevisionId, premiseRevisionIds, structureProgress)
            : undefined,
          draft.kind === 'ATTEMPT'
            ? researchAttemptWrite(
                attemptTargetRevisionId,
                attemptOutcome,
                attemptFindings,
                attemptResultRevisionId,
                attemptEvidence,
              )
            : undefined,
        ),
      };
      const serialized = JSON.stringify(body);
      if (receipt?.body !== serialized) receipt = { body: serialized, key: crypto.randomUUID() };
      const result = await records.create(body, receipt.key);
      saved = result.outputs.find((output) => output.entity_type === 'OBJECT_VERSION')!.entity_id;
      receipt = undefined;
      await query.invalidateQueries({ queryKey: ['records', projectId] });
      await query.invalidateQueries({ queryKey: ['objects', projectId] });
      creating = false;
    } catch (cause) {
      error = `${explain(cause)} Your draft is retained.`;
    } finally {
      busy = false;
    }
  }
</script>

{#if revisionId}
  <a href={`/workspaces/${projectId}/records`}
    >← {publicWorkspace ? 'Workspace research' : 'Workspace research'}</a
  >
  {#if $selected.isPending}<LoadingState>Loading exact version…</LoadingState>
  {:else if $selected.isError}<Alert.Root variant="destructive" role="alert"
      >{explain($selected.error)}</Alert.Root
    >
    <Button type="submit" onclick={() => $selected.refetch()}>Retry</Button>
  {:else if $selected.data}
    {@const record = $selected.data}
    <h1>{record.content.title}</h1>
    <p>
      {record.kind} · {record.authorship.actor_kind === 'AGENT'
        ? record.authorship.agent_display_name
        : record.authorship.author_display_name} · Version {record.number}
    </p>
    <p>
      Reported outcome: {record.content.reported_outcome ?? 'UNASSESSED'}. This is not independent
      verification.
    </p>
    <Markdown content={record.content.content_md} />
    <h2>Assumptions</h2>
    <Markdown content={record.content.assumptions_md} />
    {#if record.content.explanation_md}<h2>Explanation</h2>
      <Markdown content={record.content.explanation_md} />{/if}
    <h2>Exact statement targets</h2>
    <ul>
      {#each statementObjectVersionIds(record) as target (target)}<li>
          <a href={`/workspaces/${projectId}/records/${target}`}>{target}</a>
        </li>{:else}<li>No statement targets.</li>{/each}
    </ul>
    <RecordEdit {record} {projectId} {canWrite} />
    {#if canWrite && (record.content.source_language ?? sourceLanguage(record.legacy_kind ?? record.kind))}
      {@const language =
        record.content.source_language ?? sourceLanguage(record.legacy_kind ?? record.kind)!}
      {@const sourceKey = `${projectId}:${record.object_id}:source`}
      {@const source = {
        objectId: record.object_id,
        revisionId: record.id,
        language,
        content: record.content.content_md,
        href: sourceHref(record.id),
      } satisfies SourceRevisionView}
      {#await import('./VersionedSourceEditor.svelte')}<LoadingState
          >Loading source editor…</LoadingState
        >
      {:then module}<module.default
          {source}
          initialDraft={sourceDrafts.get(sourceKey)}
          onDraftChange={(value: SourceRevisionDraft) => sourceDrafts.set(sourceKey, { ...value })}
          save={async (value: SourceRevisionDraft) => {
            const snapshot = editableVersionSnapshot(await api.getVersion(value.baseRevisionId));
            snapshot.content.content_md = value.content;
            snapshot.change_summary = `Update ${value.language} source`;
            const result = await api.createVersion(record.object_id, {
              expected_current_object_version_id: value.baseRevisionId,
              snapshot,
            });
            const saved = {
              ...source,
              revisionId: result.current_object_version_id,
              content: value.content,
              href: sourceHref(result.current_object_version_id),
            };
            sourceDrafts.set(sourceKey, {
              ...value,
              baseRevisionId: saved.revisionId,
              content: saved.content,
            });
            await query.invalidateQueries({ queryKey: ['records', projectId] });
            await query.invalidateQueries({ queryKey: ['objects', projectId] });
            await query.invalidateQueries({
              queryKey: ['object', projectId, record.object_id],
            });
            return saved;
          }}
          loadCurrent={async () => {
            const current = await api.getObject(projectId, record.object_id);
            const currentLanguage =
              current.current_object_version.content.source_language ??
              sourceLanguage(current.current_object_version.legacy_kind ?? current.kind);
            if (!currentLanguage)
              throw new Error('The current object is no longer editable source.');
            return {
              objectId: current.id,
              revisionId: current.current_object_version_id,
              language: currentLanguage,
              content: current.current_object_version.content.content_md,
              href: sourceHref(current.current_object_version_id),
            };
          }}
        />{/await}
    {/if}
    {#await import('./ResearchContextPanel.svelte')}<LoadingState
        >Loading research context…</LoadingState
      >
    {:then module}<module.default {record} {projectId} {canWrite} {canPublish} />{/await}
    {#await import('./ScopedRelations.svelte') then module}<module.default
        {revisionId}
        {projectId}
        {canWrite}
      />{/await}
  {/if}
{:else}
  <h1>{publicWorkspace ? 'Workspace research' : 'Workspace research'}</h1>
  <form
    class="toolbar"
    onsubmit={(event) => {
      event.preventDefault();
      applied = { q: search, status: outcome || undefined, author: author || undefined };
    }}
  >
    <Field.Label>Search workspace research<Input type="search" bind:value={search} /></Field.Label>
    <Field.Label
      >Filter reported outcome<NativeSelect bind:value={outcome}
        ><option value="">All outcomes</option
        >{#each ['UNASSESSED', 'IN_PROGRESS', 'FAILED', 'PARTIAL', 'SUCCEEDED'] as value (value)}<option
            >{value}</option
          >{/each}</NativeSelect
      ></Field.Label
    >
    <Field.Label>Filter author<Input bind:value={author} /></Field.Label>
    <Button type="submit">{publicWorkspace ? 'Search research' : 'Search research'}</Button>
  </form>
  <p>
    Notes, ideas, attempts, proofs, discussions, and supporting statements.
    {publicWorkspace
      ? 'Saved research in this workspace is public.'
      : 'Saving here does not publish research.'}
  </p>
  {#if canWrite}<Button
      type="submit"
      onclick={() => {
        creating = !creating;
        saved = '';
      }}>Add research</Button
    >{/if}
  {#if saved}<p role="status">
      {publicWorkspace ? 'Saved publicly.' : 'Saved privately.'}
      <a href={`/workspaces/${projectId}/records/${saved}`}>Read saved version</a>
    </p>{/if}
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if creating && canWrite}<form
      class="panel"
      onsubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <Field.Label
        >Kind<NativeSelect bind:value={draft.kind}
          >{#each ['NOTE', 'STATEMENT', 'DEFINITION', 'PROBLEM', 'PROOF', 'ATTEMPT', 'FORMALIZATION'] as kind (kind)}<option
              >{kind}</option
            >{/each}</NativeSelect
        ></Field.Label
      >
      <Field.Label>Title<Input required maxlength={500} bind:value={draft.title} /></Field.Label>
      <Field.Label
        >{draft.kind === 'FORMALIZATION' ? 'Saved source' : 'Research'}<Textarea
          required
          rows={8}
          maxlength={100000}
          bind:value={draft.content_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Assumptions<Textarea required maxlength={20000} bind:value={draft.assumptions_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Exact statement version IDs (optional)<Textarea bind:value={targets}
        ></Textarea></Field.Label
      >
      <p>
        Separate IDs with spaces or commas. Targets must be accessible public statements or
        statements in this workspace; later versions are never selected automatically.
      </p>
      {#if draft.kind === 'PROOF'}
        <ProofStructureFields bind:conclusionRevisionId bind:premiseRevisionIds />
        <Field.Label
          >Reported sketch progress<NativeSelect bind:value={structureProgress}
            >{#each ['POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED'] as value (value)}<option
                >{value}</option
              >{/each}</NativeSelect
          ></Field.Label
        >
      {:else if draft.kind === 'ATTEMPT'}
        <fieldset>
          <legend>Research attempt structure</legend>
          <Field.Label
            >Exact target version ID<Input
              required
              bind:value={attemptTargetRevisionId}
            /></Field.Label
          >
          <Field.Label
            >Attempt outcome<NativeSelect bind:value={attemptOutcome}
              >{#each ['POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED'] as value (value)}<option
                  >{value}</option
                >{/each}</NativeSelect
            ></Field.Label
          >
          <Field.Label
            >Findings<Textarea required maxlength={100000} bind:value={attemptFindings}
            ></Textarea></Field.Label
          >
          <Field.Label
            >Exact result version ID (optional)<Input
              bind:value={attemptResultRevisionId}
            /></Field.Label
          >
          <Field.Label
            >Evidence (optional; one <code>ROLE: object-version-id</code> per line)<Textarea
              bind:value={attemptEvidence}
              placeholder="SUPPORTS: exact-object-version-id"
            ></Textarea></Field.Label
          >
          <p class="muted">Roles are INPUT, SUPPORTS, CONTRADICTS, or OUTPUT.</p>
        </fieldset>
      {/if}
      <Field.Label
        >Reported outcome<NativeSelect bind:value={draft.reported_outcome}
          >{#each ['UNASSESSED', 'IN_PROGRESS', 'FAILED', 'PARTIAL', 'SUCCEEDED'] as outcome (outcome)}<option
              >{outcome}</option
            >{/each}</NativeSelect
        ></Field.Label
      >
      <Field.Label
        >Explanation (optional)<Textarea maxlength={20000} bind:value={draft.explanation_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Change summary (optional)<Textarea maxlength={4000} bind:value={draft.change_summary}
        ></Textarea></Field.Label
      >
      <Button type="submit" disabled={busy}
        >{publicWorkspace ? 'Save public research' : 'Save private research'}</Button
      >
    </form>{/if}
  {#if $listing.isPending}<LoadingState>Loading research…</LoadingState>
  {:else if $listing.isError}<Alert.Root variant="destructive" role="alert"
      >{explain($listing.error)}</Alert.Root
    >
    <Button type="submit" onclick={() => $listing.refetch()}>Retry</Button>
  {:else}
    {#each $listing.data?.pages.flatMap((page) => page.items) ?? [] as record (record.id)}<article
        class="panel"
      >
        <h2>
          <a href={`/workspaces/${projectId}/records/${record.id}`}>{record.content.title}</a>
        </h2>
        <p>
          {record.kind} · {record.authorship.actor_kind === 'AGENT'
            ? record.authorship.agent_display_name
            : record.authorship.author_display_name} · {record.content.reported_outcome ??
            'UNASSESSED'}
        </p>
        {#if record.content.explanation_md}<Markdown content={record.content.explanation_md} />{/if}
      </article>{:else}<p>No research records yet.</p>{/each}
    {#if $listing.hasNextPage}<Button
        type="submit"
        disabled={$listing.isFetchingNextPage}
        onclick={() => $listing.fetchNextPage()}>Load more research</Button
      >{/if}
  {/if}
{/if}
