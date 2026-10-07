<script lang="ts">
  import { proofStructure, statementObjectVersionIds } from '../lib/version-snapshot';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { untrack } from 'svelte';
  import type { components } from '@polycolab/api-client';
  import { workspace, explain } from '../svelte-lib/context';
  import {
    coarseKind,
    exactRevision,
    mapAuthoredSummary,
    mapAuthoredSummaryRevision,
    mapHumanNote,
    mapProofSketch,
    mapResearchAttempt,
    mapResearchComment,
    mapResearchProgress,
  } from '../lib/research-structure-mappers';
  import ResearchAttemptHistory from './ResearchAttemptHistory.svelte';
  import ResearchSummaries from './ResearchSummaries.svelte';
  import ResearchActivity from './ResearchActivity.svelte';
  import ResearchActivityActions from './ResearchActivityActions.svelte';
  import HumanNote from './HumanNote.svelte';
  import AssuranceActions from './AssuranceActions.svelte';
  import ProofAssurance from './ProofAssurance.svelte';
  import ArtifactAccess from './ArtifactAccess.svelte';
  import { mapArtifactAttachments } from '../lib/artifact-view';
  import { MAX_ARTIFACT_UPLOAD_BYTES, saveArtifactDownload } from '../lib/artifact-api';

  type RecordRead = import('../lib/research-api').ObjectVersion;
  type AttemptPage = components['schemas']['ObjectVersionPage'];
  type NoteRead = components['schemas']['HumanNoteRead'];
  type NotePage = components['schemas']['HumanNotePage'];
  type SummaryRead = components['schemas']['ResearchSummaryVersionRead'];
  type SummaryPage = components['schemas']['ResearchSummaryVersionPage'];
  type CommentPage = components['schemas']['ResearchCommentVersionPage'];
  type ProgressPage = components['schemas']['ResearchProgressVersionPage'];
  type AssuranceRead = components['schemas']['ObjectVersionAssuranceRead'];
  type AssuranceCurrentRead = components['schemas']['ObjectVersionCurrentAssuranceRead'];
  type ObjectVersionDisplayRead = components['schemas']['ObjectVersionDisplayRead'];
  type ArtifactAttachmentPage = components['schemas']['Collection_ArtifactAttachmentItem_'];

  let {
    record,
    projectId,
    canWrite,
    canPublish = false,
  }: { record: RecordRead; projectId: string; canWrite: boolean; canPublish?: boolean } = $props();
  const { researchStructure, artifacts: artifactApi } = workspace();
  let attempts = $state<AttemptPage>({ items: [], next_cursor: null });
  let note = $state<NoteRead>();
  let noteHistory = $state<NotePage>({ items: [], next_cursor: null });
  let summary = $state<SummaryRead>();
  let summaryHistory = $state<SummaryPage>({ items: [], next_cursor: null });
  let comments = $state<CommentPage>({ items: [], next_cursor: null });
  let progress = $state<ProgressPage>({ items: [], next_cursor: null });
  let assurance = $state<AssuranceRead>({
    object_version_id: untrack(() => record.id),
    endorsements: [],
    correspondence: [],
  });
  let currentAssurance = $state<AssuranceCurrentRead>({
    object_version_id: untrack(() => record.id),
    endorsements: [],
    correspondence: [],
    next_cursor: null,
  });
  let pending = $state(true);
  let loadingAttempts = $state(false);
  let loadingNoteHistory = $state(false);
  let loadingSummaryHistory = $state(false);
  let loadingActivity = $state(false);
  let loadingAssuranceHistory = $state(false);
  let loadingCurrentAssurance = $state(false);
  let loadingArtifacts = $state(false);
  let error = $state('');
  let displays = $state<Record<string, ObjectVersionDisplayRead>>({});
  let artifactAttachments = $state<ArtifactAttachmentPage>({ items: [], next_cursor: null });

  const href = (revisionId: string) => `/workspaces/${projectId}/records/${revisionId}`;
  const resolve = (revisionId: string) => ({
    title:
      revisionId === record.id
        ? record.content.title
        : (displays[revisionId]?.title ?? `Version ${revisionId}`),
    href: href(revisionId),
    objectId: revisionId === record.id ? record.object_id : displays[revisionId]?.object_id,
  });
  const target = $derived(exactRevision(record, href(record.id)));
  const revisionView = (revisionId: string) => {
    const display = displays[revisionId];
    return {
      objectId: revisionId === record.id ? record.object_id : (display?.object_id ?? revisionId),
      revisionId,
      kind:
        revisionId === record.id
          ? coarseKind(record.kind)
          : display
            ? coarseKind(display.kind)
            : ('RECORD' as const),
      title:
        revisionId === record.id
          ? record.content.title
          : (display?.title ?? `Version ${revisionId}`),
      href: href(revisionId),
    };
  };
  const artifactViews = $derived(mapArtifactAttachments(artifactAttachments.items, revisionView));
  const attemptViews = $derived(
    attempts.items
      .map((item) => mapResearchAttempt(item, resolve))
      .filter((item) => item !== undefined),
  );
  const artifactAttemptTargets = $derived(
    attempts.items
      .filter((item) => item.kind === 'ATTEMPT' && !item.legacy_unstructured)
      .map((item) => exactRevision(item, href(item.id))),
  );
  const proofView = $derived(
    mapProofSketch(
      record,
      currentAssurance,
      assurance,
      resolve,
      href(record.id),
      proofStructure(record)?.conclusionObjectVersionId ?? record.id,
    ),
  );

  async function optional<T>(request: Promise<T>): Promise<T | undefined> {
    try {
      return await request;
    } catch (cause) {
      const status = (cause as { status?: number }).status;
      if (status === 403 || status === 404) return undefined;
      throw cause;
    }
  }

  async function loadDisplays(revisionIds: string[]) {
    const unique = [...new Set(revisionIds)].filter((id) => id !== record.id);
    const batches = Array.from({ length: Math.ceil(unique.length / 128) }, (_, index) =>
      unique.slice(index * 128, (index + 1) * 128),
    );
    const pages = await Promise.all(
      batches.map((object_version_ids) =>
        researchStructure.objectVersionDisplays({ workspace_id: projectId, object_version_ids }),
      ),
    );
    displays = {
      ...displays,
      ...Object.fromEntries(
        pages.flatMap((page) => page.items).map((item) => [item.object_version_id, item]),
      ),
    };
  }

  const attemptRevisionIds = (items: AttemptPage['items']) =>
    items.flatMap((item) =>
      item.structural_relationships
        .filter((relationship) =>
          ['TARGET', 'EVIDENCE', 'RESULT'].includes(relationship.relationship_type),
        )
        .map((relationship) => relationship.target_object_version_id),
    );

  async function load() {
    pending = true;
    error = '';
    try {
      const [
        attemptPage,
        noteRead,
        notePage,
        summaryRead,
        summaryPage,
        commentPage,
        progressPage,
        assuranceRead,
        currentAssuranceRead,
        artifactPage,
      ] = await Promise.all([
        researchStructure.attempts(record.object_id, {
          workspace_id: projectId,
          target_object_version_id: record.id,
        }),
        optional(researchStructure.humanNote(record.object_id, projectId)),
        optional(researchStructure.humanNoteHistory(record.object_id, { workspace_id: projectId })),
        optional(researchStructure.summary(record.object_id, projectId)),
        optional(researchStructure.summaryHistory(record.object_id, { workspace_id: projectId })),
        researchStructure.comments(record.object_id, {
          workspace_id: projectId,
          object_version_id: record.id,
        }),
        researchStructure.progress(record.object_id, {
          workspace_id: projectId,
          object_version_id: record.id,
        }),
        researchStructure.assurance(record.id, projectId),
        researchStructure.currentAssurance(record.id, projectId),
        artifactApi.attachments(projectId, { object_version_id: record.id }),
      ]);
      attempts = attemptPage;
      note = noteRead;
      noteHistory = notePage ?? { items: [], next_cursor: null };
      summary = summaryRead;
      summaryHistory = summaryPage ?? { items: [], next_cursor: null };
      comments = commentPage;
      progress = progressPage;
      assurance = assuranceRead;
      currentAssurance = currentAssuranceRead;
      artifactAttachments = artifactPage;
      await loadDisplays([
        ...statementObjectVersionIds(record),
        ...record.structural_relationships.map(
          (relationship) => relationship.target_object_version_id,
        ),
        ...attemptRevisionIds(attemptPage.items),
        ...(summaryRead?.current_revision.source_object_version_ids ?? []),
        ...(summaryPage?.items.flatMap((item) => item.source_object_version_ids) ?? []),
        ...assuranceRead.correspondence.map((item) => item.statement_object_version_id),
        ...currentAssuranceRead.correspondence.map((item) => item.statement_object_version_id),
        ...artifactPage.items.flatMap((item) => [
          item.object_version_id,
          ...(item.source_object_version_id ? [item.source_object_version_id] : []),
          ...(item.attempt_object_version_id ? [item.attempt_object_version_id] : []),
        ]),
      ]);
    } catch (cause) {
      error = explain(cause);
    } finally {
      pending = false;
    }
  }

  async function reloadActivity() {
    [comments, progress] = await Promise.all([
      researchStructure.comments(record.object_id, {
        workspace_id: projectId,
        object_version_id: record.id,
      }),
      researchStructure.progress(record.object_id, {
        workspace_id: projectId,
        object_version_id: record.id,
      }),
    ]);
  }

  async function loadMoreAttempts() {
    if (!attempts.next_cursor || loadingAttempts) return;
    loadingAttempts = true;
    try {
      const next = await researchStructure.attempts(record.object_id, {
        workspace_id: projectId,
        target_object_version_id: record.id,
        cursor: attempts.next_cursor,
      });
      await loadDisplays(attemptRevisionIds(next.items));
      attempts = { ...next, items: [...attempts.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingAttempts = false;
    }
  }

  async function loadMoreNoteHistory() {
    if (!noteHistory.next_cursor || loadingNoteHistory) return;
    loadingNoteHistory = true;
    try {
      const next = await researchStructure.humanNoteHistory(record.object_id, {
        workspace_id: projectId,
        cursor: noteHistory.next_cursor,
      });
      noteHistory = { ...next, items: [...noteHistory.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingNoteHistory = false;
    }
  }

  async function loadMoreSummaryHistory() {
    if (!summaryHistory.next_cursor || loadingSummaryHistory) return;
    loadingSummaryHistory = true;
    try {
      const next = await researchStructure.summaryHistory(record.object_id, {
        workspace_id: projectId,
        cursor: summaryHistory.next_cursor,
      });
      await loadDisplays(next.items.flatMap((item) => item.source_object_version_ids));
      summaryHistory = { ...next, items: [...summaryHistory.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingSummaryHistory = false;
    }
  }

  async function loadMoreActivity() {
    if (loadingActivity) return;
    loadingActivity = true;
    try {
      const [nextComments, nextProgress] = await Promise.all([
        comments.next_cursor
          ? researchStructure.comments(record.object_id, {
              workspace_id: projectId,
              object_version_id: record.id,
              cursor: comments.next_cursor,
            })
          : Promise.resolve(undefined),
        progress.next_cursor
          ? researchStructure.progress(record.object_id, {
              workspace_id: projectId,
              object_version_id: record.id,
              cursor: progress.next_cursor,
            })
          : Promise.resolve(undefined),
      ]);
      if (nextComments)
        comments = { ...nextComments, items: [...comments.items, ...nextComments.items] };
      if (nextProgress)
        progress = { ...nextProgress, items: [...progress.items, ...nextProgress.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingActivity = false;
    }
  }

  async function loadMoreAssuranceHistory() {
    if (!assurance.next_cursor || loadingAssuranceHistory) return;
    loadingAssuranceHistory = true;
    try {
      const next = await researchStructure.assurance(
        record.id,
        projectId,
        50,
        assurance.next_cursor,
      );
      await loadDisplays(next.correspondence.map((item) => item.statement_object_version_id));
      assurance = {
        ...next,
        endorsements: [...assurance.endorsements, ...next.endorsements],
        correspondence: [...assurance.correspondence, ...next.correspondence],
      };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingAssuranceHistory = false;
    }
  }

  async function loadMoreCurrentAssurance() {
    if (!currentAssurance.next_cursor || loadingCurrentAssurance) return;
    loadingCurrentAssurance = true;
    try {
      const next = await researchStructure.currentAssurance(
        record.id,
        projectId,
        50,
        currentAssurance.next_cursor,
      );
      await loadDisplays(next.correspondence.map((item) => item.statement_object_version_id));
      currentAssurance = {
        ...next,
        endorsements: [...currentAssurance.endorsements, ...next.endorsements],
        correspondence: [...currentAssurance.correspondence, ...next.correspondence],
      };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingCurrentAssurance = false;
    }
  }

  async function loadMoreArtifacts() {
    if (!artifactAttachments.next_cursor || loadingArtifacts) return;
    loadingArtifacts = true;
    try {
      const next = await artifactApi.attachments(projectId, {
        object_version_id: record.id,
        cursor: artifactAttachments.next_cursor,
      });
      await loadDisplays(
        next.items.flatMap((item) => [
          item.object_version_id,
          ...(item.source_object_version_id ? [item.source_object_version_id] : []),
          ...(item.attempt_object_version_id ? [item.attempt_object_version_id] : []),
        ]),
      );
      artifactAttachments = {
        ...next,
        items: [...artifactAttachments.items, ...next.items],
      };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingArtifacts = false;
    }
  }

  async function reloadArtifacts() {
    artifactAttachments = await artifactApi.attachments(projectId, {
      object_version_id: record.id,
    });
    await loadDisplays(
      artifactAttachments.items.flatMap((item) => [
        item.object_version_id,
        ...(item.source_object_version_id ? [item.source_object_version_id] : []),
        ...(item.attempt_object_version_id ? [item.attempt_object_version_id] : []),
      ]),
    );
  }

  $effect(() => {
    untrack(() => void load());
  });
</script>

<section aria-labelledby={`research-context-${record.id}`}>
  <h2 id={`research-context-${record.id}`}>Exact research context</h2>
  {#if pending}<LoadingState>Loading exact attempts, notes, summaries and assurance…</LoadingState>
  {:else if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>
    <Button type="submit" onclick={() => void load()}>Retry context</Button>
  {:else}
    {#if proofView}<ProofAssurance
        alternatives={[proofView]}
        currentStatementRevisionId={proofView.conclusion.revisionId}
        hasMoreCurrent={Boolean(currentAssurance.next_cursor)}
        loadingMoreCurrent={loadingCurrentAssurance}
        onLoadMoreCurrent={() => void loadMoreCurrentAssurance()}
        hasMoreHistory={Boolean(assurance.next_cursor)}
        loadingMoreHistory={loadingAssuranceHistory}
        onLoadMoreHistory={() => void loadMoreAssuranceHistory()}
      />{/if}
    <ResearchAttemptHistory
      {target}
      attempts={attemptViews}
      hasMore={Boolean(attempts.next_cursor)}
      loadingMore={loadingAttempts}
      onLoadMore={() => void loadMoreAttempts()}
    />
    {#if note}<HumanNote
        objectId={record.object_id}
        objectTitle={record.content.title}
        note={mapHumanNote(note, noteHistory.items)}
        canEdit={note.can_edit}
        save={async (draft, key) => {
          const saved = await researchStructure.writeHumanNote(
            record.object_id,
            {
              workspace_id: projectId,
              base_revision_id: draft.baseRevisionId,
              body_md: draft.content,
            },
            key,
          );
          note = saved;
          return mapHumanNote(saved, noteHistory.items).current;
        }}
        loadCurrent={async () => {
          const current = await researchStructure.humanNote(record.object_id, projectId);
          note = current;
          return mapHumanNote(current, noteHistory.items).current;
        }}
        hasMoreHistory={Boolean(noteHistory.next_cursor)}
        loadingMoreHistory={loadingNoteHistory}
        loadMoreHistory={() => void loadMoreNoteHistory()}
      />{:else}<HumanNote
        objectId={record.object_id}
        objectTitle={record.content.title}
        canEdit={canWrite}
        save={async (draft, key) => {
          const saved = await researchStructure.writeHumanNote(
            record.object_id,
            { workspace_id: projectId, body_md: draft.content },
            key,
          );
          note = saved;
          return mapHumanNote(saved, []).current;
        }}
      />{/if}
    <ResearchSummaries
      authored={summary ? mapAuthoredSummary(summary, resolve) : undefined}
      canEdit={canWrite}
      defaultSourceRevisionId={record.id}
      history={summaryHistory.items.map((item) => mapAuthoredSummaryRevision(item, resolve))}
      hasMoreHistory={Boolean(summaryHistory.next_cursor)}
      loadingMoreHistory={loadingSummaryHistory}
      loadMoreHistory={() => void loadMoreSummaryHistory()}
      save={async (content, sourceRevisionIds, baseRevisionId, key) => {
        summary = await researchStructure.writeSummary(
          record.object_id,
          {
            workspace_id: projectId,
            base_revision_id: baseRevisionId,
            body_md: content,
            source_object_version_ids: sourceRevisionIds,
          },
          key,
        );
        return mapAuthoredSummary(summary, resolve);
      }}
    />
    <ResearchActivity
      targetRevisionId={record.id}
      targetKind={coarseKind(record.kind)}
      comments={comments.items.map(mapResearchComment)}
      progress={progress.items.map(mapResearchProgress)}
      hasMore={Boolean(comments.next_cursor || progress.next_cursor)}
      onLoadMore={() => void loadMoreActivity()}
    />
    {#if canWrite}<ResearchActivityActions
        targetRevisionId={record.id}
        comment={(body, key) =>
          researchStructure.comment(
            record.object_id,
            { workspace_id: projectId, object_version_id: record.id, body_md: body },
            key,
          )}
        progress={(status, detail, key) =>
          researchStructure.reportProgress(
            record.object_id,
            {
              workspace_id: projectId,
              object_version_id: record.id,
              status,
              detail_md: detail,
            },
            key,
          )}
        onSaved={reloadActivity}
      />{/if}
    {#if canWrite}<AssuranceActions
        revisionId={record.id}
        {projectId}
        statementTargets={statementObjectVersionIds(record).map((revisionId) => ({
          revisionId,
          title: resolve(revisionId).title,
        }))}
        endorse={(draft, key) => researchStructure.endorse(draft, key)}
        assessCorrespondence={(draft, key) => researchStructure.assessCorrespondence(draft, key)}
      />{/if}
    <ArtifactAccess
      artifacts={artifactViews}
      targets={[target]}
      attempts={artifactAttemptTargets}
      maxUploadBytes={MAX_ARTIFACT_UPLOAD_BYTES}
      canUpload={canWrite}
      hasMore={Boolean(artifactAttachments.next_cursor)}
      loadingMore={loadingArtifacts}
      onLoadMore={() => void loadMoreArtifacts()}
      upload={async (draft) => {
        await artifactApi.uploadAndAttach(projectId, draft);
        await reloadArtifacts();
      }}
      download={async (artifactId) => {
        const blob = await artifactApi.download(projectId, artifactId);
        saveArtifactDownload(blob, artifactId);
      }}
    />
    {#await import('./PublicationPanel.svelte')}<LoadingState
        >Loading publication workflow…</LoadingState
      >
    {:then module}<module.default
        {projectId}
        {record}
        {summary}
        comments={comments.items}
        progress={progress.items}
        artifacts={artifactViews}
        {canPublish}
      />{/await}
  {/if}
</section>

<style>
  section {
    display: grid;
    gap: 1rem;
  }
  h2 {
    margin-top: 0;
  }
</style>
