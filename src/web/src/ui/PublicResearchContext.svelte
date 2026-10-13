<script lang="ts">
  import { proofStructure } from '../lib/version-snapshot';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { onMount, untrack } from 'svelte';
  import type { components } from '$lib/api-client';
  import { projectContext, explain } from '../svelte-lib/context';
  import {
    exactRevision,
    mapProofSketch,
    mapResearchAttempt,
  } from '../lib/research-structure-mappers';
  import ProofAssurance from './ProofAssurance.svelte';
  import ResearchAttemptHistory from './ResearchAttemptHistory.svelte';

  type RecordRead = import('../lib/research-api').ObjectVersion;
  type AttemptPage = components['schemas']['ObjectVersionPage'];
  type AssuranceRead = components['schemas']['ObjectVersionAssuranceRead'];
  type AssuranceCurrentRead = components['schemas']['ObjectVersionCurrentAssuranceRead'];

  let { record }: { record: RecordRead } = $props();
  const { researchStructure } = projectContext();
  let attempts = $state<AttemptPage>({ items: [], next_cursor: null });
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
  let loadingMore = $state(false);
  let loadingAssuranceHistory = $state(false);
  let loadingCurrentAssurance = $state(false);
  let error = $state('');

  const href = (revisionId: string) => `/commons/records/${revisionId}`;
  const resolve = (revisionId: string) => ({
    title: revisionId === record.id ? record.content.title : `Version ${revisionId}`,
    href: href(revisionId),
    objectId: revisionId === record.id ? record.object_id : undefined,
  });
  const target = $derived(exactRevision(record, href(record.id)));
  const proof = $derived(
    mapProofSketch(
      record,
      currentAssurance,
      assurance,
      resolve,
      href(record.id),
      proofStructure(record)?.conclusionObjectVersionId ?? record.id,
    ),
  );

  async function load() {
    pending = true;
    error = '';
    try {
      const [attemptPage, assuranceRead, currentAssuranceRead] = await Promise.all([
        record.kind === 'ATTEMPT'
          ? Promise.resolve({ items: [], next_cursor: null })
          : researchStructure.publicAttempts(record.object_id, record.id),
        researchStructure.publicAssurance(record.id),
        researchStructure.publicCurrentAssurance(record.id),
      ]);
      attempts = attemptPage;
      assurance = assuranceRead;
      currentAssurance = currentAssuranceRead;
    } catch (cause) {
      error = explain(cause);
    } finally {
      pending = false;
    }
  }

  async function more() {
    if (!attempts.next_cursor || loadingMore) return;
    loadingMore = true;
    try {
      const next = await researchStructure.publicAttempts(record.object_id, record.id, {
        cursor: attempts.next_cursor,
      });
      attempts = { ...next, items: [...attempts.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      loadingMore = false;
    }
  }

  async function moreAssuranceHistory() {
    if (!assurance.next_cursor || loadingAssuranceHistory) return;
    loadingAssuranceHistory = true;
    try {
      const next = await researchStructure.publicAssurance(record.id, 50, assurance.next_cursor);
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

  async function moreCurrentAssurance() {
    if (!currentAssurance.next_cursor || loadingCurrentAssurance) return;
    loadingCurrentAssurance = true;
    try {
      const next = await researchStructure.publicCurrentAssurance(
        record.id,
        50,
        currentAssurance.next_cursor,
      );
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

  onMount(() => void load());
</script>

<section aria-labelledby={`public-research-context-${record.id}`}>
  <h2 id={`public-research-context-${record.id}`}>Public research context</h2>
  {#if pending}<LoadingState>Loading public attempts and assurance…</LoadingState>
  {:else if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>
    <Button type="submit" onclick={() => void load()}>Retry context</Button>
  {:else}
    {#if proof}<ProofAssurance
        alternatives={[proof]}
        currentStatementRevisionId={proof.conclusion.revisionId}
        hasMoreCurrent={Boolean(currentAssurance.next_cursor)}
        loadingMoreCurrent={loadingCurrentAssurance}
        onLoadMoreCurrent={() => void moreCurrentAssurance()}
        hasMoreHistory={Boolean(assurance.next_cursor)}
        loadingMoreHistory={loadingAssuranceHistory}
        onLoadMoreHistory={() => void moreAssuranceHistory()}
      />{/if}
    {#if record.kind !== 'ATTEMPT'}<ResearchAttemptHistory
        {target}
        attempts={attempts.items
          .map((item) => mapResearchAttempt(item, resolve))
          .filter((item) => item !== undefined)}
        hasMore={Boolean(attempts.next_cursor)}
        loadingMore
        onLoadMore={() => void more()}
      />{/if}
    <p class="muted">Private human notes are never part of this public surface.</p>
  {/if}
</section>

<style>
  section {
    display: grid;
    gap: 1rem;
  }
  h2,
  p {
    margin-top: 0;
  }
</style>
