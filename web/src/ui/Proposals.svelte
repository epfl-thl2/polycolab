<script lang="ts">
  import { Checkbox } from '../lib/components/ui/checkbox';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Badge } from '../lib/components/ui/badge';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Input } from '../lib/components/ui/input';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { untrack } from 'svelte';
  import { workspace, explain } from '../svelte-lib/context';
  import { ProposalApiError, type ProposalBatchDecision } from '../lib/proposals-api';
  import {
    editProposalText,
    proposalAcceptanceEdit,
    proposalTextFields,
    proposalTextValue,
  } from '../lib/proposal-editor';
  import Markdown from './Markdown.svelte';
  let { projectId, proposalId }: { projectId: string; proposalId?: string } = $props();
  const { proposals, query } = workspace();
  let selected = $state<string[]>([]);
  let edited = $state<Record<string, string>>({});
  let actions = $state<Record<string, 'ACCEPT' | 'REJECT'>>({});
  let reason = $state('');
  let error = $state('');
  let busy = $state(false);
  let notice = $state('');
  let receipt: { body: string; key: string } | undefined;
  const inbox = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['proposals', projectId],
      enabled: !proposalId,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        proposals.listProjectProposals(projectId, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const detail = createQuery(
    toStore(() => ({
      queryKey: ['proposal', proposalId],
      enabled: Boolean(proposalId),
      queryFn: () => proposals.getProposal(proposalId!),
    })),
  );
  const context = createQuery(
    toStore(() => ({
      queryKey: ['proposal-context', proposalId],
      enabled: Boolean(proposalId),
      queryFn: () => proposals.getContext(proposalId!),
    })),
  );
  $effect(() => {
    const changes = $detail.data?.changes;
    if (changes)
      for (const change of changes) {
        if (untrack(() => edited[change.id]) === undefined)
          edited[change.id] = JSON.stringify(change.payload, null, 2);
      }
  });
  async function decide(event: SubmitEvent) {
    event.preventDefault();
    if (!proposalId) return;
    busy = true;
    error = '';
    notice = '';
    try {
      const decisions: ProposalBatchDecision[] = selected.map((id) => ({
        change_id: id,
        action: actions[id] ?? 'ACCEPT',
        ...((actions[id] ?? 'ACCEPT') === 'ACCEPT'
          ? proposalAcceptanceEdit(
              $detail.data!.changes.find((change) => change.id === id)!.payload,
              edited[id],
            )
          : { reason: reason || undefined }),
      }));
      const body = JSON.stringify(decisions);
      if (receipt?.body !== body) receipt = { body, key: crypto.randomUUID() };
      await proposals.decideChanges(proposalId, decisions, receipt.key);
      selected = [];
      receipt = undefined;
      await query.invalidateQueries({ queryKey: ['proposal', proposalId] });
      await query.invalidateQueries({ queryKey: ['objects', projectId] });
      notice = 'Selected decisions applied together.';
    } catch (problem) {
      error =
        problem instanceof SyntaxError
          ? 'The edited payload is not valid JSON. Your draft is retained.'
          : explain(problem);
    } finally {
      busy = false;
    }
  }
</script>

<h1>Proposal review</h1>
<p class="muted">
  Review suggested changes individually or apply a selected set atomically. Acceptance records your
  decision; it is not formal verification.
</p>
{#if !proposalId}{#if $inbox.isPending}<LoadingState>
      Loading proposals…
    </LoadingState>{:else if $inbox.isError}<Alert.Root variant="destructive" role="alert"
      >{explain($inbox.error)}</Alert.Root
    >
    <Button type="submit" onclick={() => $inbox.refetch()}>Retry</Button>{:else}<ul class="list">
      {#each $inbox.data?.pages.flatMap((p) => p.items) ?? [] as proposal (proposal.id)}<li>
          <a href={`/workspaces/${projectId}/proposals/${proposal.id}`}>{proposal.summary}</a>
          <p class="muted">{new Date(proposal.created_at).toLocaleString()}</p>
        </li>{/each}
    </ul>
    {#if !$inbox.data?.pages[0].items.length}<p class="empty">
        No proposals to review.
      </p>{/if}{/if}{#if $inbox.hasNextPage}<Button
      type="submit"
      onclick={() => $inbox.fetchNextPage()}>Load more proposals</Button
    >{/if}
{:else if $detail.isPending}<LoadingState>
    Loading proposal…
  </LoadingState>{:else if $detail.isError || $detail.data?.workspace_id !== projectId}<Alert.Root
    variant="destructive"
    role="alert"
  >
    Proposal unavailable. Return to the inbox.
  </Alert.Root>{:else if $detail.data}
  <a href={`/workspaces/${projectId}/proposals`}>← Proposal inbox</a>
  <h2 class="mt-6">{$detail.data.summary}</h2>
  <p class="muted">Agent version {$detail.data.agent_version_id}</p>
  {#if $context.isPending}<LoadingState>Loading exact proposal context…</LoadingState>
  {:else if $context.isError}
    {#if $context.error instanceof ProposalApiError && $context.error.status === 404}<section
        class="card"
        aria-label="Proposal source context"
      >
        <h2>Sources private to requesting contributor</h2>
        <p>
          You can review the structured proposal changes, but the originating run and its exact
          context remain private to the contributor who requested them.
        </p>
      </section>{:else}<div role="alert" class="notice">
        Exact proposal context could not be loaded.
        <Button variant="outline" class="" type="button" onclick={() => $context.refetch()}
          >Retry proposal context</Button
        >
      </div>{/if}
  {:else if $context.data}<section class="card" aria-label="Proposal source context">
      <h2>Exact object versions supplied to the agent</h2>
      <p class="muted">
        Manifest {$context.data.id} · digest <code>{$context.data.digest}</code> · {$context.data
          .object_version_ids.length} exact object versions · {$context.data.artifact_ids.length} exact
        artifacts
      </p>
      <ul class="list">
        {#each $context.data.object_versions as version (version.id)}<li>
            <strong>{version.content.title}</strong> · version {version.number}
            <p class="muted">
              Exact source <code>{version.id}</code> · {version.authorship.actor_kind.toLowerCase()} ·
              {version.authorship.agent_display_name ??
                version.authorship.author_display_name ??
                'Project member'}
            </p>
            <details>
              <summary>Show source content</summary>
              <pre><code>{version.content.content_md}</code></pre>
            </details>
          </li>{/each}
      </ul>
      {#if $context.data.artifact_ids.length}<h3>Exact artifact references</h3>
        <ul class="list">
          {#each $context.data.artifact_ids as artifactId (artifactId)}<li>
              <code>{artifactId}</code>
            </li>{/each}
        </ul>{/if}
    </section>{/if}
  <form onsubmit={decide}>
    {#each $detail.data.changes as change (change.id)}<section class="card">
        <div class="row">
          <h3 class="grow">
            {String(change.payload.kind ?? change.change_type).replaceAll('_', ' ')}
          </h3>
          <Badge variant="outline">{change.status}</Badge>
        </div>
        {#each proposalTextFields(change.payload).filter( (field) => ['content_md', 'body_md'].includes(field.path.at(-1) ?? '') ) as field (field.path.join('.'))}
          <Markdown content={field.value} />
        {/each}
        {#if change.status === 'PENDING'}<Field.Label class="row"
            ><Checkbox
              checked={selected.includes(change.id)}
              onCheckedChange={(checked) => {
                selected = checked
                  ? [...selected, change.id]
                  : selected.filter((item) => item !== change.id);
              }}
              value={change.id}
            /> Select change {change.ordinal}</Field.Label
          ><Field.Label class="mt-4"
            >Decision for change {change.ordinal}<NativeSelect
              value={actions[change.id] ?? 'ACCEPT'}
              onchange={(e) => (actions[change.id] = e.currentTarget.value as 'ACCEPT' | 'REJECT')}
              ><option value="ACCEPT">Accept (including edits below)</option><option value="REJECT"
                >Reject</option
              ></NativeSelect
            ></Field.Label
          >{#each proposalTextFields(change.payload) as field (field.path.join('.'))}<Field.Label
              class="mt-4"
              >{field.label}<Textarea
                value={proposalTextValue(JSON.parse(edited[change.id] || '{}'), field.path)}
                oninput={(event) => {
                  const payload = JSON.parse(edited[change.id]);
                  edited[change.id] = JSON.stringify(
                    editProposalText(payload, field.path, event.currentTarget.value),
                    null,
                    2,
                  );
                }}
              ></Textarea></Field.Label
            >{/each}
          <details>
            <summary>Exact object-version references and submitted change</summary>
            <pre>{JSON.stringify(change.payload, null, 2)}</pre>
          </details>{:else}<pre>{JSON.stringify(change.payload, null, 2)}</pre>
          <p class="muted">
            Decided by {change.decided_by_user_id} · {change.rejection_reason ?? ''}
          </p>{/if}
      </section>{/each}
    <Field.Label>Reason for selected rejections<Input bind:value={reason} /></Field.Label
    >{#if error}<div role="alert" class="notice">
        {error}<Button variant="outline" class="" type="button" onclick={() => $detail.refetch()}
          >Refresh proposal, keep drafts</Button
        >
      </div>{/if}{#if notice}<p role="status">{notice}</p>{/if}<Button
      type="submit"
      disabled={busy || !selected.length}
      >{busy ? 'Applying…' : `Apply ${selected.length} selected decisions`}</Button
    >
  </form>{/if}

<style>
  pre {
    overflow-x: auto;
    white-space: pre-wrap;
  }
</style>
