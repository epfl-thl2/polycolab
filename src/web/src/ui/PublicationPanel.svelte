<script lang="ts">
  import { listReviews, type Review } from '../lib/reviews-api';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { onMount } from 'svelte';
  import type { components } from '$lib/api-client';
  import { projectContext, explain } from '../svelte-lib/context';
  import {
    mapPublicationManifest,
    mapPublicationPreview,
    publicationSelection,
  } from '../lib/publication-mappers';
  import type { PublicationSelectionItem } from '../lib/publication-view';
  import PublicationWorkflow from './PublicationWorkflow.svelte';
  import PublicationHistory from './PublicationHistory.svelte';
  import type { ArtifactView } from '../lib/artifact-view';

  type RecordRead = import('../lib/research-api').ObjectVersion;
  type SummaryRead = components['schemas']['ResearchSummaryVersionRead'];
  type CommentRead = components['schemas']['ResearchCommentVersionRead'];
  type ProgressRead = components['schemas']['ResearchProgressVersionRead'];
  type RelationRead = import('../lib/research-api').Relation;
  type ManifestPage = components['schemas']['PublicationVersionManifestPage'];

  let {
    projectId,
    record,
    summary,
    comments,
    progress,
    artifacts = [],
    canPublish,
  }: {
    projectId: string;
    record: RecordRead;
    summary?: SummaryRead;
    comments: CommentRead[];
    progress: ProgressRead[];
    artifacts?: ArtifactView[];
    canPublish: boolean;
  } = $props();
  const { publication, records } = projectContext();
  let reviews = $state<Review[]>([]);
  let reviewCursor = $state<string>();
  let relations = $state<RelationRead[]>([]);
  let history = $state<ManifestPage>({ items: [], next_cursor: null });
  let pending = $state(true);
  let loadingMore = $state(false);
  let error = $state('');
  let previewSelection = $state<components['schemas']['PublicationVersionSelection']>();

  const available = $derived.by(() => {
    const items: PublicationSelectionItem[] = [
      {
        id: record.id,
        revisionId: record.id,
        kind:
          record.kind === 'ATTEMPT'
            ? 'RESEARCH_ATTEMPT'
            : record.kind === 'PROOF'
              ? 'PROOF'
              : 'RESEARCH_REVISION',
        title: record.content.title,
        href: `/projects/${projectId}/records/${record.id}`,
        description: 'Exact research version',
      },
    ];
    if (summary)
      items.push({
        id: summary.current_revision.id,
        revisionId: summary.current_revision.id,
        kind: 'AUTHORED_SUMMARY',
        title: `Authored summary revision ${summary.current_revision.number}`,
        href: `/projects/${projectId}/records/${record.id}`,
      });
    items.push(
      ...comments.map((comment) => ({
        id: comment.id,
        revisionId: comment.object_version_id,
        kind: 'COMMENT' as const,
        title: `Comment by ${comment.author_display_name ?? comment.agent_display_name ?? 'Unknown contributor'}`,
        href: `/projects/${projectId}/records/${comment.object_version_id}`,
      })),
      ...progress.map((item) => ({
        id: item.id,
        revisionId: item.object_version_id,
        kind: 'PROGRESS' as const,
        title: `${item.status} progress`,
        href: `/projects/${projectId}/records/${item.object_version_id}`,
      })),
      ...relations.map((relation) => ({
        id: relation.id,
        kind: 'RELATION' as const,
        title: `${relation.relationship_type} relationship`,
        href: `/projects/${projectId}/records/${relation.direction === 'BIDIRECTIONAL' ? relation.first_object_version_id : relation.source_object_version_id}`,
      })),
      ...artifacts
        .filter((artifact) => artifact.state === 'COMMITTED')
        .map((artifact) => ({
          id: artifact.artifactId,
          revisionId: artifact.researchRevision.revisionId,
          kind: 'ARTIFACT' as const,
          title: `Artifact ${artifact.artifactId}`,
          href: artifact.researchRevision.href,
          description: `${artifact.digest} · ${artifact.byteLength.toLocaleString()} bytes · ${artifact.mediaType}`,
        })),
    );
    items.push(
      ...reviews.map((review) => ({
        id: review.id,
        revisionId: review.object_version_id,
        kind: 'REVIEW' as const,
        title: `${review.actor_kind === 'HUMAN' ? 'Human' : 'AI'} review by ${review.reviewer_name}`,
        href: `/projects/${projectId}/objects/${record.object_id}?panel=reviews`,
        description: `${review.withdrawn ? 'Withdrawn' : review.outcome} · ${review.scope}`,
      })),
    );
    return items;
  });

  async function load() {
    pending = true;
    error = '';
    try {
      const [relationPage, manifestPage, reviewPage] = await Promise.all([
        records.relationPage(record.id, undefined, projectId),
        publication.history(projectId),
        listReviews(record.id, projectId, undefined, true, true),
      ]);
      relations = relationPage.items;
      history = manifestPage;
      reviews = reviewPage.items;
      reviewCursor = reviewPage.next_cursor ?? undefined;
    } catch (cause) {
      error = explain(cause);
    } finally {
      pending = false;
    }
  }

  async function moreHistory() {
    if (!history.next_cursor || loadingMore) return;
    loadingMore = true;
    try {
      const next = await publication.history(projectId, 25, history.next_cursor);
      history = { ...next, items: [...history.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingMore = false;
    }
  }

  onMount(() => void load());
</script>

<section aria-labelledby={`publication-${record.id}`}>
  <h2 id={`publication-${record.id}`}>Publish exact research</h2>
  {#if pending}<LoadingState>Loading publication choices and history…</LoadingState>
  {:else if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>
    <Button type="submit" onclick={() => void load()}>Retry publication data</Button>
  {:else}
    {#if reviewCursor}<Button
        variant="outline"
        onclick={async () => {
          try {
            const next = await listReviews(record.id, projectId, reviewCursor, true, true);
            reviews = [...reviews, ...next.items];
            reviewCursor = next.next_cursor ?? undefined;
          } catch (cause) {
            error = explain(cause);
          }
        }}>Load more review choices</Button
      >{/if}
    <PublicationWorkflow
      {available}
      actorKind="HUMAN"
      {canPublish}
      createPreview={async (draft) => {
        const requested = publicationSelection(projectId, available, draft.selectedIds);
        const preview = await publication.preview(requested);
        previewSelection = preview.selection;
        return mapPublicationPreview(preview);
      }}
      confirmPublication={async (confirmation, key) => {
        if (!previewSelection || confirmation.digest !== confirmation.previewId)
          throw new Error('The exact preview selection is no longer available.');
        const manifest = await publication.confirm(
          {
            ...previewSelection,
            preview_digest: confirmation.digest,
            reason: confirmation.reason,
          },
          key,
        );
        history = { ...history, items: [manifest, ...history.items] };
        return mapPublicationManifest(manifest);
      }}
    />
    <PublicationHistory manifests={history.items.map(mapPublicationManifest)} />
    {#if history.next_cursor}<Button
        type="submit"
        variant="outline"
        class=""
        disabled={loadingMore}
        onclick={() => void moreHistory()}
        >{loadingMore ? 'Loading publication history…' : 'Load more publication history'}</Button
      >{/if}
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
