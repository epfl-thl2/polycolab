<script lang="ts">
  import { ArrowUpRight, LocateFixed } from '@lucide/svelte';
  import LoadingState from './LoadingState.svelte';
  import * as Dialog from '../lib/components/ui/dialog';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import Markdown from './Markdown.svelte';
  import RelativeTime from './RelativeTime.svelte';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { workspace, explain } from '../svelte-lib/context';
  import type { ObjectKind, ObjectVersion, VersionSnapshot } from '../lib/research-api';
  import type { PrimaryResearchAction } from './PrimaryResearchActions.svelte';
  import type { RevisionChoice } from './ResearchRevisionSelector.svelte';
  import ResearchRevisionSelector from './ResearchRevisionSelector.svelte';

  let {
    projectId,
    canWrite,
    publicRead = false,
    overview = false,
    selected = $bindable(),
    oninspect = () => {},
  }: {
    projectId: string;
    canWrite: boolean;
    publicRead?: boolean;
    overview?: boolean;
    selected?: { version: ObjectVersion; searchResult: boolean };
    oninspect?: () => void;
  } = $props();
  const { api, records, query } = workspace();
  let showCreation = $state(false);
  let searchDraft = $state('');
  let appliedSearch = $state('');
  const objects = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['objects', projectId, publicRead],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listObjects(projectId, publicRead, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  const searchResults = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['research-object-search', projectId, publicRead, appliedSearch],
      enabled: Boolean(appliedSearch),
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        (publicRead ? records.publicSearch : records.workspaceSearch)({
          workspace_id: projectId,
          q: appliedSearch,
          cursor: pageParam,
        }),
      getNextPageParam: (page: { next_cursor: string | null }) => page.next_cursor ?? undefined,
    })),
  );
  const rows = $derived(
    appliedSearch
      ? ($searchResults.data?.pages.flatMap((page) => page.items) ?? []).map(
          ({ object_version: version }) => ({
            id: version.object_id,
            versionId: version.id,
            kind: version.kind,
            version,
          }),
        )
      : ($objects.data?.pages.flatMap((page) => page.items) ?? []).map((object) => ({
          id: object.id,
          versionId: object.current_object_version.id,
          kind: object.kind,
          version: object.current_object_version,
        })),
  );
  function applySearch(event: SubmitEvent) {
    event.preventDefault();
    selected = undefined;
    appliedSearch = searchDraft.trim();
  }
  let action = $state<PrimaryResearchAction>('PROBLEM_OR_CLAIM');
  let statementKind = $state<'PROBLEM' | 'STATEMENT' | 'DEFINITION' | 'NOTE' | 'FORMALIZATION'>(
    'PROBLEM',
  );
  let attachmentObjectId = $state('');
  let formalizationVersionId = $state('');
  let sourceLanguage = $state<'' | 'LEAN' | 'PYTHON'>('');
  let statementLabel = $state<
    'CLAIM' | 'CONJECTURE' | 'LEMMA' | 'PROPOSITION' | 'THEOREM' | 'COROLLARY'
  >('CLAIM');
  let proofDirection = $state<'SUPPORTS' | 'REFUTES'>('SUPPORTS');
  let title = $state('');
  let content = $state('');
  let rationale = $state('');
  let targetRevisionId = $state('');
  let evidenceRevisionId = $state('');
  let outputRevisionIds = $state('');
  let attemptOutcome = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let findings = $state('');
  let conclusionRevisionId = $state('');
  let premiseRevisionId = $state('');
  let premiseRevisionIds = $state<string[]>([]);
  let sketchProgress = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let error = $state('');
  let busy = $state(false);

  const attachmentChoices = createQuery(
    toStore(() => ({
      queryKey: ['attachment-objects', projectId],
      enabled: showCreation,
      queryFn: async () => {
        const objects = [];
        let cursor: string | undefined;
        do {
          const page = await api.listObjects(projectId, false, cursor);
          objects.push(...page.items);
          cursor = page.nextCursor;
        } while (cursor);
        return objects;
      },
    })),
  );
  const kindForAction = (selected: PrimaryResearchAction): ObjectKind =>
    selected === 'PROBLEM_OR_CLAIM' ? statementKind : selected === 'ATTEMPT' ? 'ATTEMPT' : 'PROOF';

  async function searchRevisions(search: string): Promise<RevisionChoice[]> {
    const pages = await Promise.all([
      records.workspaceSearch({ workspace_id: projectId, q: search, limit: 25 }),
      records.publicSearch({ q: search, limit: 25 }),
    ]);
    const matches = new Map(
      pages.flatMap((page) =>
        page.items.map(({ object_version: record }) => [record.id, record] as const),
      ),
    );
    return [...matches.values()].map((record) => ({
      revisionId: record.id,
      title: record.content.title,
      kind: record.kind,
      revisionNumber: record.number,
    }));
  }

  function addPremise() {
    if (!premiseRevisionId || premiseRevisionIds.includes(premiseRevisionId)) return;
    if (premiseRevisionId === conclusionRevisionId) {
      error = 'A conclusion cannot also be its own premise.';
      return;
    }
    premiseRevisionIds = [...premiseRevisionIds, premiseRevisionId];
    premiseRevisionId = '';
    error = '';
  }

  function resetForm() {
    action = 'PROBLEM_OR_CLAIM';
    statementKind = 'PROBLEM';
    statementLabel = 'CLAIM';
    proofDirection = 'SUPPORTS';
    sourceLanguage = '';
    attachmentObjectId = '';
    formalizationVersionId = '';
    title = '';
    content = '';
    rationale = '';
    targetRevisionId = '';
    evidenceRevisionId = '';
    outputRevisionIds = '';
    findings = '';
    conclusionRevisionId = '';
    premiseRevisionId = '';
    premiseRevisionIds = [];
    error = '';
  }

  async function create(event: SubmitEvent) {
    event.preventDefault();
    if (!action) return;
    busy = true;
    error = '';
    try {
      const common = {
        change_summary: rationale.trim() || null,
        content: {
          source_language: sourceLanguage || null,
          title: title.trim(),
          content_md: content,
          assumptions_md: 'None stated',
          reported_outcome: 'UNASSESSED' as const,
          explanation_md: null,
        },
      };
      let snapshot: VersionSnapshot;
      if (action === 'ATTEMPT') {
        snapshot = {
          ...common,
          kind: 'ATTEMPT',
          content: { ...common.content, outcome: attemptOutcome, findings_md: findings },
          structural_relationships: [
            { relationship_type: 'TARGET', target_object_version_id: targetRevisionId },
            ...[...new Set(outputRevisionIds.split(/[\s,]+/).filter(Boolean))].map(
              (id, position) => ({
                relationship_type: 'EVIDENCE' as const,
                target_object_version_id: id,
                evidence_role: 'OUTPUT' as const,
                position: position + (evidenceRevisionId ? 1 : 0),
              }),
            ),
            ...(evidenceRevisionId
              ? [
                  {
                    relationship_type: 'EVIDENCE' as const,
                    target_object_version_id: evidenceRevisionId,
                    position: 0,
                    evidence_role: 'SUPPORTS' as const,
                  },
                ]
              : []),
          ],
        };
      } else if (action === 'PROOF') {
        snapshot = {
          ...common,
          kind: 'PROOF',
          content: {
            ...common.content,
            reported_progress: sketchProgress,
            direction: proofDirection,
          },
          structural_relationships: [
            ...[conclusionRevisionId, ...premiseRevisionIds].map((id) => ({
              relationship_type: 'ATTACHMENT' as const,
              target_object_version_id: id,
            })),
            { relationship_type: 'CONCLUSION', target_object_version_id: conclusionRevisionId },
            ...premiseRevisionIds.map((id, position) => ({
              relationship_type: 'PREMISE' as const,
              target_object_version_id: id,
              position,
            })),
          ],
        };
      } else {
        const kind = kindForAction(action);
        if (kind === 'ATTEMPT' || kind === 'PROOF') throw new Error('Invalid research action');
        snapshot = {
          ...common,
          kind,
          content: {
            ...common.content,
            statement_label: kind === 'STATEMENT' ? statementLabel : null,
            attached_object_ids: kind === 'NOTE' && attachmentObjectId ? [attachmentObjectId] : [],
          },
          structural_relationships:
            kind === 'FORMALIZATION' && formalizationVersionId
              ? [
                  {
                    relationship_type: 'ATTACHMENT',
                    target_object_version_id: formalizationVersionId,
                  },
                ]
              : [],
        };
      }
      const object = await api.createObject(projectId, snapshot);
      await query.invalidateQueries({ queryKey: ['objects', projectId] });
      resetForm();
      showCreation = false;
      await goto(`/workspaces/${projectId}/objects/${object.id}`);
    } catch (reason) {
      error = `${explain(reason)} Your draft and exact selections are retained.`;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open={showCreation}>
  <div class="heading research-heading">
    <div>
      <h1>Research objects</h1>
      {#if !overview && (appliedSearch ? $searchResults.data : $objects.data)}<p class="muted">
          {rows.length}
          {appliedSearch
            ? rows.length === 1
              ? 'matching object'
              : 'matching objects'
            : rows.length === 1
              ? 'object'
              : 'objects'}
        </p>{/if}
    </div>
    {#if canWrite}<Dialog.Trigger class={buttonVariants({ variant: 'outline' })}
        >Create object</Dialog.Trigger
      >{/if}
  </div>

  <form class="research-search" role="search" onsubmit={applySearch}>
    <Input
      type="search"
      aria-label="Search research objects"
      placeholder="Search objects…"
      bind:value={searchDraft}
    />
    <Button type="submit" variant="outline">Search</Button>
    {#if appliedSearch}<Button
        type="button"
        variant="ghost"
        onclick={() => {
          selected = undefined;
          searchDraft = '';
          appliedSearch = '';
        }}>Clear</Button
      >{/if}
  </form>

  {#if canWrite}
    <Dialog.Content
      class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl"
      style="--muted: var(--polycolab-groseille-soft)"
      showCloseButton={!busy}
      onInteractOutside={(event) => {
        if (busy) event.preventDefault();
      }}
      onEscapeKeydown={(event) => {
        if (busy) event.preventDefault();
      }}
    >
      <Dialog.Header
        ><Dialog.Title>Create object</Dialog.Title><Dialog.Description
          >Choose an object type and enter its content.</Dialog.Description
        ></Dialog.Header
      >
      <form class="research-create-form" onsubmit={create}>
        <Field.Label
          >Object type<NativeSelect
            value={kindForAction(action)}
            disabled={busy}
            onchange={(event) => {
              const kind = event.currentTarget.value;
              if (
                kind === 'PROBLEM' ||
                kind === 'STATEMENT' ||
                kind === 'DEFINITION' ||
                kind === 'NOTE' ||
                kind === 'FORMALIZATION'
              ) {
                statementKind = kind;
                action = 'PROBLEM_OR_CLAIM';
              } else if (kind === 'ATTEMPT' || kind === 'PROOF') action = kind;
            }}
            ><option value="PROBLEM">Problem</option><option value="STATEMENT">Statement</option
            ><option value="DEFINITION">Definition</option><option value="NOTE">Note</option><option
              value="FORMALIZATION">Formalization</option
            ><option value="ATTEMPT">Attempt</option><option value="PROOF">Proof</option
            ></NativeSelect
          ></Field.Label
        >
        {#if kindForAction(action) === 'NOTE'}
          <Field.Label
            >Attach to object<NativeSelect
              bind:value={attachmentObjectId}
              disabled={$attachmentChoices.isPending}
            >
              <option value="">No attachment</option>
              {#each $attachmentChoices.data ?? [] as object (object.id)}<option value={object.id}
                  >{object.current_object_version.content.title}</option
                >{/each}
            </NativeSelect></Field.Label
          >
          {#if $attachmentChoices.isError}<p role="alert">
              {explain($attachmentChoices.error)}
            </p>{/if}
        {/if}
        {#if kindForAction(action) === 'FORMALIZATION'}<ResearchRevisionSelector
            label="Formalized version"
            required
            search={searchRevisions}
            bind:value={formalizationVersionId}
          />{/if}
        {#if kindForAction(action) === 'STATEMENT'}
          <Field.Label
            >Statement label<NativeSelect bind:value={statementLabel}>
              <option value="CLAIM">Claim</option><option value="CONJECTURE">Conjecture</option
              ><option value="LEMMA">Lemma</option><option value="PROPOSITION">Proposition</option
              ><option value="THEOREM">Theorem</option><option value="COROLLARY">Corollary</option>
            </NativeSelect></Field.Label
          >
        {/if}
        {#if kindForAction(action) === 'PROOF'}
          <Field.Label
            >Argument direction<NativeSelect bind:value={proofDirection}
              ><option value="SUPPORTS">Supports the statement</option><option value="REFUTES"
                >Refutes the statement</option
              ></NativeSelect
            ></Field.Label
          >
        {/if}
        <Field.Label
          >Title<Input
            placeholder="Give this object a clear title"
            required
            maxlength={500}
            bind:value={title}
          /></Field.Label
        >
        <Field.Label
          >Content <span class="muted">Markdown supported</span><Textarea
            class="min-h-32"
            placeholder="Describe the question, statement, or approach…"
            required
            maxlength={100000}
            bind:value={content}
          ></Textarea></Field.Label
        >
        <Field.Label
          >Executable source<NativeSelect bind:value={sourceLanguage}
            ><option value="">None</option><option value="LEAN">Lean</option><option value="PYTHON"
              >Python</option
            ></NativeSelect
          ></Field.Label
        >
        <details class="creation-context">
          <summary>Add context <span class="muted">(optional)</span></summary><Field.Label
            >Reason or context<Textarea maxlength={4000} bind:value={rationale} /></Field.Label
          >
        </details>

        {#if action === 'ATTEMPT'}
          <ResearchRevisionSelector
            label="Attempt target"
            required
            search={searchRevisions}
            bind:value={targetRevisionId}
          />
          <Field.Label
            >Outcome<NativeSelect bind:value={attemptOutcome}
              >{#each ['POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED'] as value (value)}<option
                  >{value}</option
                >{/each}</NativeSelect
            ></Field.Label
          >
          <Field.Label
            >What was learned<Textarea required maxlength={100000} bind:value={findings}
            ></Textarea></Field.Label
          >
          <ResearchRevisionSelector
            label="Supporting evidence"
            search={searchRevisions}
            bind:value={evidenceRevisionId}
          />
          <Field.Label
            >Output version IDs (optional)<Textarea
              bind:value={outputRevisionIds}
              placeholder="Exact versions produced by this attempt, separated by commas"
            /></Field.Label
          >
        {:else if action === 'PROOF'}
          <ResearchRevisionSelector
            label="Conclusion"
            required
            search={async (search) =>
              (await searchRevisions(search)).filter((choice) => choice.kind === 'STATEMENT')}
            bind:value={conclusionRevisionId}
          />
          <ResearchRevisionSelector
            label="Premise to add"
            search={searchRevisions}
            bind:value={premiseRevisionId}
          />
          <Button
            variant="outline"
            type="button"
            class=""
            disabled={!premiseRevisionId}
            onclick={addPremise}>Add exact premise</Button
          >
          <ol class="list">
            {#each premiseRevisionIds as revisionId (revisionId)}<li>
                <code>{revisionId}</code><Button
                  variant="outline"
                  type="button"
                  class=""
                  onclick={() =>
                    (premiseRevisionIds = premiseRevisionIds.filter((id) => id !== revisionId))}
                  >Remove</Button
                >
              </li>{:else}<li>No premises selected.</li>{/each}
          </ol>
          <Field.Label
            >Reported progress<NativeSelect bind:value={sketchProgress}
              >{#each ['POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED'] as value (value)}<option
                  >{value}</option
                >{/each}</NativeSelect
            ></Field.Label
          >
        {/if}

        {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
        <div class="creation-footer">
          <Button
            variant="outline"
            disabled={busy}
            onclick={() => {
              resetForm();
              showCreation = false;
            }}>Cancel</Button
          ><Button type="submit" disabled={busy || !title.trim() || !content.trim()}
            >{busy ? 'Creating…' : 'Create object'}</Button
          >
        </div>
      </form>
    </Dialog.Content>
  {/if}

  {#if appliedSearch ? $searchResults.isPending : $objects.isPending}<LoadingState
      >Loading research…</LoadingState
    >{:else if appliedSearch ? $searchResults.isError : $objects.isError}<Alert.Root
      variant="destructive"
      role="alert"
    >
      {explain(appliedSearch ? $searchResults.error : $objects.error)}
      <Button
        type="button"
        onclick={() => (appliedSearch ? $searchResults.refetch() : $objects.refetch())}
        >Retry</Button
      >
    </Alert.Root>
  {:else if !rows.length}<section class="empty">
      <h2>{appliedSearch ? 'No matching research' : 'No research objects yet'}</h2>
      <p class="muted">
        {appliedSearch
          ? 'Try another search term.'
          : 'Start with a problem or claim, an attempt, or a proof sketch.'}
      </p>
    </section>
  {:else}<section class="research-list" aria-label="Research object results">
      {#if overview}<h2>All objects</h2>{/if}
      {#if !overview}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard access to horizontally scrollable table.) -->
        <div
          class="object-table-scroll workspace-data-table"
          role="region"
          aria-label="Research objects table"
          tabindex="0"
        >
          <table aria-label="Research objects">
            <colgroup
              ><col /><col style="width: 115px" /><col style="width: 65px" /><col
                style="width: 115px"
              /><col style="width: 76px" /></colgroup
            >
            <thead
              ><tr
                ><th scope="col">Object</th><th scope="col">Type</th><th scope="col">Version</th><th
                  scope="col">Last updated</th
                ><th scope="col">ID</th></tr
              ></thead
            >
            <tbody>
              {#each rows as row (row.versionId)}
                <tr
                  class:selected={selected?.version.id === row.versionId}
                  onclick={(event) => {
                    if ((event.target as Element).closest('a')) return;
                    selected = { version: row.version, searchResult: Boolean(appliedSearch) };
                    oninspect();
                  }}
                >
                  <td class="object-title-cell">
                    <div class="object-title-actions">
                      <button
                        class="table-title"
                        aria-pressed={selected?.version.id === row.versionId}
                        onclick={(event) => {
                          event.stopPropagation();
                          selected = { version: row.version, searchResult: Boolean(appliedSearch) };
                          oninspect();
                        }}>{row.version.content.title}</button
                      >
                      <a
                        class="object-open"
                        href={`/workspaces/${projectId}/map?object=${encodeURIComponent(row.id)}`}
                        aria-label={`Focus on map: ${row.version.content.title}`}
                        title="Focus on map"><LocateFixed size={14} aria-hidden="true" /></a
                      >
                      <a
                        class="object-open"
                        href={`/workspaces/${projectId}/objects/${row.id}`}
                        aria-label={`Open object: ${row.version.content.title}`}
                        title="Open object"><ArrowUpRight size={14} aria-hidden="true" /></a
                      >
                    </div>
                  </td>
                  <td><ObjectKindBadge kind={row.kind} /></td>
                  <td class="table-metadata">v{row.version.number}</td>
                  <td class="object-updated"><RelativeTime value={row.version.created_at} /></td>
                  <td class="object-id" title={row.id} aria-label={`Object ID ${row.id}`}
                    >{row.id.slice(0, 4)}...</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <ul aria-label="Research objects">
          {#each rows as row (row.versionId)}<li>
              <div class="object-primary">
                <h3>
                  <a href={`/workspaces/${projectId}/objects/${row.id}`}
                    >{row.version.content.title}</a
                  >
                </h3>
                <div class="object-meta">
                  <ObjectKindBadge kind={row.kind} /><span>v{row.version.number}</span>
                </div>
              </div>
              {#if overview}<div class="object-excerpt">
                  <Markdown content={row.version.content.content_md} />
                </div>{/if}
              <p class="object-byline">
                {row.version.authorship.author_display_name || 'Member'} · <RelativeTime
                  value={row.version.created_at}
                />
              </p>
            </li>{/each}
        </ul>
      {/if}
    </section>{/if}

  {#if appliedSearch ? $searchResults.hasNextPage : $objects.hasNextPage}<Button
      type="button"
      variant="outline"
      class=""
      disabled={appliedSearch ? $searchResults.isFetchingNextPage : $objects.isFetchingNextPage}
      onclick={() => (appliedSearch ? $searchResults.fetchNextPage() : $objects.fetchNextPage())}
      >Load more research</Button
    >{/if}
</Dialog.Root>

<style>
  .research-heading,
  .research-search {
    --muted: var(--polycolab-groseille-soft);
  }
  .research-heading h1 {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }
  .research-heading {
    align-items: center;
    margin-bottom: 18px;
  }
  .research-heading p {
    margin: 4px 0 0;
    font-size: 12px;
  }
  .research-search {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 18px;
  }
  .research-search :global(input) {
    flex: 1;
    min-width: 0;
  }
  .research-list {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel);
    overflow: hidden;
  }
  .research-list h2 {
    margin: 0;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    font-weight: 600;
  }
  .object-table-scroll {
    overflow-x: auto;
  }
  .object-table-scroll table {
    min-width: 556px;
  }
  .object-id {
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .object-title-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .object-title-actions .table-title {
    flex: 1;
    min-width: 0;
  }
  .object-open {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    color: var(--muted-foreground);
    border-radius: 4px;
  }
  .object-open:hover {
    background: var(--brand-soft);
    color: var(--foreground);
  }
  .object-open:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .object-title-cell {
    min-width: 160px;
  }
  .object-updated {
    color: var(--muted-foreground);
    font-size: 12px;
  }

  .research-list ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .research-list li {
    padding: 12px 16px;
  }
  .research-list li + li {
    border-top: 1px solid var(--border);
  }
  .research-list li:hover {
    background: var(--panel-muted);
  }
  .object-primary {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px 16px;
  }
  .object-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .research-list h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 500;
    overflow-wrap: anywhere;
  }
  .research-list h3 a {
    color: var(--foreground);
    text-decoration: none;
  }
  .research-list h3 a:hover {
    text-decoration: underline;
  }
  .object-excerpt {
    max-height: 4.5em;
    overflow: hidden;
    color: var(--muted-foreground);
    font-size: 14px;
  }
  .object-excerpt :global(.prose > :first-child) {
    margin-top: 0;
  }
  .object-excerpt :global(.prose > :last-child) {
    margin-bottom: 0;
  }
  .object-byline {
    margin: 4px 0 0;
    color: var(--muted-foreground);
    font-size: 12px;
  }

  .creation-context {
    font-size: 13px;
  }
  .creation-context summary {
    cursor: pointer;
    margin-bottom: 8px;
    color: var(--muted-foreground);
  }
  .creation-footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    border-top: 1px solid var(--border);
    padding-top: 16px;
  }
  .research-create-form {
    display: grid;
    gap: 1rem;
  }
  code {
    overflow-wrap: anywhere;
  }
  @media (max-width: 600px) {
    .object-primary {
      display: grid;
      gap: 6px;
    }
  }
</style>
