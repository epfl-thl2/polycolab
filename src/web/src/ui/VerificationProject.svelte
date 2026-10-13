<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  import { onMount } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import { mapVerificationJob, verificationRevisionIds } from '../lib/verification-mappers';
  import type { VerificationEventRead, VerificationJobRead } from '../lib/verification-api';
  import type { VerificationJobView } from '../lib/verification-view';
  import VerificationJob from './VerificationJob.svelte';

  let { projectId, jobId, canWrite }: { projectId: string; jobId?: string; canWrite: boolean } =
    $props();
  const { verification, researchStructure, capabilities } = projectContext();
  const canSubmit = $derived(
    canWrite && (capabilities?.enabled('verification_submission') ?? false),
  );
  let lookup = $state('');
  let job = $state<VerificationJobView>();
  let snapshot = $state<VerificationJobRead>();
  let events = $state<VerificationEventRead[]>([]);
  let pending = $state(true);
  let interrupted = $state(false);
  let error = $state('');
  let requestGeneration = 0;

  async function displaysFor(value: VerificationJobRead) {
    const ids = [...new Set(verificationRevisionIds(value))];
    const pages = await Promise.all(
      Array.from({ length: Math.ceil(ids.length / 128) }, (_, index) =>
        researchStructure.objectVersionDisplays({
          project_id: projectId,
          object_version_ids: ids.slice(index * 128, (index + 1) * 128),
        }),
      ),
    );
    return pages.flatMap((page) => page.items);
  }

  async function load(afterSequence = 0) {
    if (!jobId) return;
    const request = ++requestGeneration;
    pending = !job;
    error = '';
    let current: VerificationJobRead;
    try {
      current = await verification.inspect(projectId, jobId);
      const displays = await displaysFor(current);
      let committed = events;
      try {
        const replay = await verification.events(projectId, jobId, afterSequence, 100);
        committed = [...events, ...replay]
          .filter(
            (event, index, all) =>
              all.findIndex((candidate) => candidate.sequence === event.sequence) === index,
          )
          .sort((left, right) => left.sequence - right.sequence);
        interrupted = false;
      } catch {
        interrupted = true;
      }
      if (request !== requestGeneration) return;
      snapshot = current;
      events = committed;
      job = mapVerificationJob(current, committed, displays);
    } catch (cause) {
      if (request === requestGeneration) error = explain(cause);
    } finally {
      if (request === requestGeneration) pending = false;
    }
  }

  async function cancel() {
    if (!jobId) return;
    await verification.cancel(projectId, jobId);
    await load(events.at(-1)?.sequence ?? 0);
  }

  async function rerun() {
    if (!jobId) return;
    const next = await verification.rerun(projectId, jobId, crypto.randomUUID());
    location.assign(`/projects/${projectId}/verification/${next.id}`);
  }

  onMount(() => {
    void load();
    return () => {
      requestGeneration += 1;
    };
  });
</script>

<section aria-labelledby="verification-title">
  <h1 id="verification-title">Verification jobs</h1>
  {#if !jobId}
    <p>
      Open an exact job identity. The current service deliberately does not expose a project job
      listing.
    </p>
    <form
      onsubmit={(event) => {
        event.preventDefault();
        if (lookup.trim()) location.assign(`/projects/${projectId}/verification/${lookup.trim()}`);
      }}
    >
      <Field.Label>Exact verification job ID<Input required bind:value={lookup} /></Field.Label>
      <Button type="submit">Inspect job</Button>
    </form>
    {#await import('./VerificationSubmission.svelte')}<LoadingState>
        Loading submission controls…
      </LoadingState>{:then module}<module.default {projectId} canWrite={canSubmit} />{/await}
  {:else if pending}
    <LoadingState>Loading exact verification job…</LoadingState>
  {:else if error}
    <Alert.Root variant="destructive" role="alert">{error}</Alert.Root>
    <Button type="submit" onclick={() => void load()}>Retry exact job</Button>
  {:else if job && snapshot}
    <VerificationJob
      {job}
      canControl={canWrite}
      isolationReady={false}
      connectionInterrupted={interrupted}
      cancel={canWrite ? cancel : undefined}
      rerun={canSubmit ? rerun : undefined}
      reconnect={(_, afterSequence) => load(afterSequence)}
    />
    <Button
      type="submit"
      variant="outline"
      class=""
      onclick={() => void load(events.at(-1)?.sequence ?? 0)}
    >
      Refresh committed state
    </Button>
  {/if}
</section>

<style>
  section,
  form {
    display: grid;
    gap: 0.75rem;
  }
  form {
    max-width: 42rem;
  }
</style>
