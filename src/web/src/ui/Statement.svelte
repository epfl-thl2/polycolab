<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { onMount } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import type { CatalogueEntry } from '../lib/catalogue-api';
  import type { NewVersionDraft } from '../lib/research-record-draft';
  import {
    proofStructureWrite,
    researchAttemptWrite,
    newVersionSnapshot,
  } from '../lib/research-record-draft';
  import ProofStructureFields from './ProofStructureFields.svelte';
  import SignIn from './SignIn.svelte';
  let { entryId }: { entryId: string } = $props();
  const { catalogue, records, community, auth } = projectContext();
  let entry = $state<CatalogueEntry>();
  let page = $state<Awaited<ReturnType<typeof records.list>>>();
  let communityState = $state<Awaited<ReturnType<typeof community.get>>>();
  let summary = $state<Awaited<ReturnType<typeof community.summary>>>();
  let interestCount = $state<number>();
  let tab = $state('Statement');
  let error = $state('');
  let busy = $state(false);
  let composing = $state(false);
  let key = crypto.randomUUID();
  let submittedPayload = '';
  let conclusionRevisionId = $state('');
  let premiseRevisionIds = $state<string[]>([]);
  let structureProgress = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let attemptOutcome = $state<'POTENTIAL' | 'PARTIAL' | 'COMPLETE' | 'STALLED' | 'FAILED'>(
    'PARTIAL',
  );
  let attemptFindings = $state('');
  let attemptResultRevisionId = $state('');
  let attemptEvidence = $state('');
  const referenceKey = crypto.randomUUID();
  let draft = $state<NewVersionDraft>({
    kind: 'ATTEMPT',
    title: '',
    content_md: '',
    assumptions_md: 'None stated',
    reported_outcome: 'IN_PROGRESS',
    change_summary: 'Record research progress',
  });
  async function load() {
    error = '';
    try {
      entry = await catalogue.get(entryId);
      if (!conclusionRevisionId) conclusionRevisionId = entry.object_version.id;
      const [researchPage, progress, participation] = await Promise.all([
        records.list({ statement_id: entry.object_version.id }),
        community.summary(entryId),
        community.interestCount(entryId),
      ]);
      page = researchPage;
      summary = progress;
      interestCount = participation.interest_count;
      if (auth.signedIn) communityState = await community.get(entryId);
    } catch (cause) {
      error = explain(cause);
    }
  }
  async function save() {
    if (!entry) return;
    busy = true;
    error = '';
    try {
      const body = {
        destination: {
          kind: 'library' as const,
          statement_object_version_id: entry.object_version.id,
        },
        snapshot: newVersionSnapshot(
          draft,
          [entry.object_version.id],
          draft.kind === 'PROOF'
            ? proofStructureWrite(conclusionRevisionId, premiseRevisionIds, structureProgress)
            : undefined,
          draft.kind === 'ATTEMPT'
            ? researchAttemptWrite(
                entry.object_version.id,
                attemptOutcome,
                attemptFindings,
                attemptResultRevisionId,
                attemptEvidence,
              )
            : undefined,
        ),
      };
      const payload = JSON.stringify(body);
      if (payload !== submittedPayload) {
        key = crypto.randomUUID();
        submittedPayload = payload;
      }
      await records.create(body, key);
      key = crypto.randomUUID();
      composing = false;
      await load();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function workPrivately() {
    if (!entry) return;
    busy = true;
    error = '';
    try {
      const ref = await records.workPrivately(
        { object_version_id: entry.object_version.id },
        referenceKey,
      );
      window.location.assign(`/projects/${ref.project_id}`);
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function toggle(follow: boolean) {
    busy = true;
    try {
      const current = communityState ?? (await community.get(entryId));
      communityState = follow
        ? await community.follow(entryId, !current.following)
        : await community.interest(entryId, !current.interested);
      interestCount = (await community.interestCount(entryId)).interest_count;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function more() {
    if (!entry || busy) return;
    busy = true;
    error = '';
    try {
      if (page?.next_cursor) {
        const next = await records.list({
          statement_id: entry.object_version.id,
          cursor: page.next_cursor,
        });
        page = { ...next, items: [...page.items, ...next.items] };
      }
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void load();
  });
</script>

<main id="main" class="page" tabindex="-1">
  <a href="/commons">← Explore public research</a>
  {#if error}<Alert.Root variant="destructive" role="alert">
      {error}
      <Button type="submit" onclick={load}>Reload saved data</Button>
    </Alert.Root>{/if}
  {#if entry}
    <h1>{entry.object_version.content.title}</h1>
    <p class="muted">
      {entry.object_version.kind} · admitted by a human {#if entry.source}· {entry.source
          .identifier}, {entry.source.version}, {entry.source.locator}{/if}
    </p>
    <p>Reported status: {entry.reported_status}. Catalogue inclusion is not verification.</p>
    {#if interestCount !== undefined}<p>
        {interestCount} people interested. Interest is not endorsement.
      </p>{/if}
    <div class="toolbar">
      {#if auth.signedIn}<Button
          type="submit"
          disabled={busy}
          onclick={() => (composing = !composing)}>Contribute research</Button
        ><Button type="submit" disabled={busy} onclick={workPrivately}>Work privately</Button
        ><Button
          type="submit"
          aria-pressed={communityState?.following ?? false}
          disabled={busy}
          onclick={() => toggle(true)}>{communityState?.following ? 'Unfollow' : 'Follow'}</Button
        ><Button
          type="submit"
          aria-pressed={communityState?.interested ?? false}
          disabled={busy}
          onclick={() => toggle(false)}
          >{communityState?.interested ? 'Withdraw interest' : 'Express interest'}</Button
        >{/if}
    </div>
    {#if !auth.signedIn}<details>
        <summary>Sign in to contribute or work privately</summary><SignIn {auth} />
      </details>{/if}
    {#if composing}<section class="panel">
        <h2>Contribute to this exact version</h2>
        <form
          onsubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field.Label
            >Kind<NativeSelect bind:value={draft.kind}
              >{#each ['NOTE', 'IDEA', 'DISCUSSION', 'STATEMENT', 'DEFINITION', 'PROBLEM', 'PROOF', 'ATTEMPT'] as value (value)}<option
                  >{value}</option
                >{/each}</NativeSelect
            ></Field.Label
          >
          <Field.Label>Title<Input required bind:value={draft.title} maxlength={500} /></Field.Label
          ><Field.Label
            >Research<Textarea required rows={7} bind:value={draft.content_md}
            ></Textarea></Field.Label
          >
          <Field.Label
            >Assumptions<Textarea bind:value={draft.assumptions_md}></Textarea></Field.Label
          >
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
              <legend>Research attempt on exact statement {entry.object_version.id}</legend>
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
              ><option>UNASSESSED</option><option>IN_PROGRESS</option><option>FAILED</option><option
                >PARTIAL</option
              ><option>SUCCEEDED</option></NativeSelect
            ></Field.Label
          >
          <Field.Label
            >Explanation (optional)<Textarea bind:value={draft.explanation_md}
            ></Textarea></Field.Label
          >
          <Field.Label
            >Change summary (optional)<Textarea bind:value={draft.change_summary}
            ></Textarea></Field.Label
          ><Button type="submit" disabled={busy}>Save public contribution</Button>
        </form>
      </section>{/if}
    <nav class="toolbar" aria-label="Statement sections">
      {#each ['Statement', 'Research', 'Proofs', 'Computations', 'Dependencies', 'Activity'] as name (name)}<Button
          type="submit"
          variant="outline"
          class=""
          aria-pressed={tab === name}
          onclick={() => (tab = name)}>{name}</Button
        >{/each}
    </nav>
    {#if tab === 'Statement'}<section class="panel">
        <h2>Formulation</h2>
        <Markdown content={entry.object_version.content.content_md} />
        <h3>Assumptions</h3>
        <Markdown content={entry.object_version.content.assumptions_md} />
        <p class="muted">Exact version: {entry.object_version.id}</p>
        <a href={`/commons/records/${entry.object_version.id}`}>Read exact version and history</a>
      </section>
      {#if auth.signedIn}{#await import('./CatalogueEdit.svelte') then module}<module.default
            {entry}
          />{/await}{/if}
    {:else if tab === 'Computations'}<p>
        Lean and Python execution are unavailable until M3. No computation or proof-check result is
        claimed here.
      </p>
    {:else if tab === 'Dependencies'}
      {#await import('./ScopedRelations.svelte') then module}<module.default
          revisionId={entry.object_version.id}
          libraryStatementObjectVersionId={entry.object_version.id}
          canWrite={auth.signedIn}
        />{/await}
    {:else if tab === 'Activity'}<h2>Source-linked progress</h2>
      <p class="muted">A bounded summary of reported research, not an assurance judgment.</p>
      {#each summary?.items ?? [] as item (item.object_version_id)}<article class="panel">
          <a href={`/commons/records/${item.object_version_id}`}>{item.title}</a>
          <p>{item.excerpt}</p>
          <p>{item.reported_outcome ?? 'Unassessed'}</p>
        </article>{:else}<p>Summary pending or no visible research.</p>{/each}
    {:else}{#each (page?.items ?? []).filter((record) => tab !== 'Proofs' || record.kind === 'PROOF') as record (record.id)}<article
          class="panel"
        >
          <p class="muted">
            {record.kind} · {record.authorship.actor_kind === 'AGENT'
              ? record.authorship.agent_display_name
              : record.authorship.author_display_name} · {record.content.reported_outcome ??
              'Unassessed'}
          </p>
          <h2><a href={`/commons/records/${record.id}`}>{record.content.title}</a></h2>
          <Markdown content={record.content.content_md} />
          {#if record.content.explanation_md}<h3>Explanation</h3>
            <Markdown content={record.content.explanation_md} />{/if}
        </article>{:else}<p>No visible {tab.toLowerCase()} yet.</p>{/each}
      {#if page?.next_cursor}<Button type="submit" disabled={busy} onclick={() => more()}
          >Load more research</Button
        >{/if}
    {/if}
  {:else if !error}<LoadingState>Loading statement…</LoadingState>{/if}
</main>
