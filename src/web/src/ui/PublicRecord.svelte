<script lang="ts">
  import ObjectReviews from './ObjectReviews.svelte';
  import { statementObjectVersionIds } from '../lib/version-snapshot';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { onMount } from 'svelte';
  import { workspace, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import type { RecordRead } from '../lib/records-api';
  let { revisionId }: { revisionId: string } = $props();
  const { records, auth } = workspace();
  let record = $state<RecordRead>();
  let error = $state('');
  let showReviews = $state(false);
  let attached = $state<Awaited<ReturnType<typeof records.list>>>();
  let attachedError = $state('');
  let loadingResearch = $state(false);
  async function loadResearch(more = false) {
    loadingResearch = true;
    attachedError = '';
    try {
      const next = await records.list({
        statement_id: revisionId,
        cursor: more ? (attached?.next_cursor ?? undefined) : undefined,
      });
      attached = more && attached ? { ...next, items: [...attached.items, ...next.items] } : next;
    } catch (cause) {
      attachedError = explain(cause);
    } finally {
      loadingResearch = false;
    }
  }
  onMount(() => {
    records
      .get(revisionId)
      .then((value) => {
        record = value;
        if (['STATEMENT', 'DEFINITION', 'PROBLEM'].includes(value.kind)) void loadResearch();
      })
      .catch((cause) => (error = explain(cause)));
  });
</script>

<main id="main" class="page" tabindex="-1">
  <a href="/commons">← Explore public research</a>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{:else if record}
    <h1>{record.content.title}</h1>

    <p>
      {record.kind} · {record.authorship.actor_kind === 'AGENT'
        ? record.authorship.agent_display_name
        : record.authorship.author_display_name}
    </p>
    <p>
      Reported outcome: {record.content.reported_outcome ?? 'Unassessed'}. Authorship is not
      endorsement or verification.
    </p>
    <Markdown content={record.content.content_md} />
    {#if record.content.explanation_md}<h2>Explanation</h2>
      <Markdown content={record.content.explanation_md} />{/if}
    {#if record.content.assumptions_md}<h2>Assumptions</h2>
      <Markdown content={record.content.assumptions_md} />{/if}
    <details bind:open={showReviews}>
      <summary>Version reviews</summary>{#if showReviews}<ObjectReviews
          versionId={record.id}
          canReview={auth.signedIn}
        />{/if}
    </details>
    <h2>Exact statement targets</h2>
    <ul>
      {#each statementObjectVersionIds(record) as target (target)}<li>
          <a href={`/commons/records/${target}`}>{target}</a>
        </li>{:else}<li>No attachments.</li>{/each}
    </ul>
    <p class="muted">Version {record.number}: {record.id}</p>
    <p class="muted">Research object: {record.object_id}</p>
    {#if record.catalogue?.source}
      <h2>Source for this exact formulation</h2>
      <p>
        {record.catalogue?.source.identifier} · {record.catalogue?.source.version} · {record
          .catalogue.source.locator}
      </p>
      <p>
        Catalogue reported status: {record.catalogue?.reported_status}. Not independent
        verification.
      </p>
      <a href={`/commons/${record.catalogue?.entry_id}`}>Read current official statement</a>
    {/if}
    {#if ['STATEMENT', 'DEFINITION', 'PROBLEM'].includes(record.kind)}
      <section class="panel">
        <h2>Research attached to this exact statement version</h2>
        <p>These targets remain pinned even when the official formulation changes.</p>
        {#if attachedError}<Alert.Root variant="destructive" role="alert"
            >{attachedError}</Alert.Root
          >
          <Button type="submit" onclick={() => loadResearch()}>Retry attached research</Button>{/if}
        {#each attached?.items ?? [] as item (item.id)}<article>
            <h3><a href={`/commons/records/${item.id}`}>{item.content.title}</a></h3>
            <p>
              {item.kind} · {item.authorship.actor_kind === 'AGENT'
                ? item.authorship.agent_display_name
                : item.authorship.author_display_name} · {item.content.reported_outcome ??
                'UNASSESSED'}
            </p>
            {#if item.content.explanation_md}<Markdown content={item.content.explanation_md} />{/if}
          </article>{:else}<p>
            {loadingResearch
              ? 'Loading attached research…'
              : 'No visible research attached to this version.'}
          </p>{/each}
        {#if attached?.next_cursor}<Button
            type="submit"
            disabled={loadingResearch}
            onclick={() => loadResearch(true)}>Load more attached research</Button
          >{/if}
      </section>
    {/if}
    {#await import('./PublicResearchContext.svelte')}<LoadingState>
        Loading public research structure…
      </LoadingState>{:then module}<module.default {record} />{/await}
    {#await import('./ScopedRelations.svelte') then module}<module.default
        {revisionId}
        canWrite={auth.signedIn}
      />{/await}
    {#if auth.signedIn && !record.catalogue?.entry_id && ['STATEMENT', 'DEFINITION', 'PROBLEM'].includes(record.kind)}{#await import('./Promotion.svelte') then module}<module.default
          {record}
        />{/await}{/if}
    {#await import('./RecordEdit.svelte') then module}<module.default
        {record}
        canWrite={auth.signedIn && !record.catalogue?.entry_id}
      />{/await}
    {#if record.catalogue?.suggestion}{#await import('./CorrectionReview.svelte') then module}<module.default
          {record}
        />{/await}{/if}
  {:else}<LoadingState>Loading research…</LoadingState>{/if}
</main>
