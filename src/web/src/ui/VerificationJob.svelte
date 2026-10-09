<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { explain } from '../svelte-lib/context';
  import type { VerificationJobView } from '../lib/verification-view';

  let {
    job,
    editorSourceRevisionId,
    canControl = false,
    isolationReady = false,
    connectionInterrupted = false,
    cancel,
    rerun,
    reconnect,
  }: {
    job: VerificationJobView;
    editorSourceRevisionId?: string;
    canControl?: boolean;
    isolationReady?: boolean;
    connectionInterrupted?: boolean;
    cancel?: (jobId: string) => Promise<unknown>;
    rerun?: (jobId: string) => Promise<unknown>;
    reconnect?: (jobId: string, afterSequence: number) => Promise<unknown>;
  } = $props();

  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  const terminal = $derived(['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(job.state));
  const staleSource = $derived(
    Boolean(editorSourceRevisionId && editorSourceRevisionId !== job.sourceRevisionId),
  );
  const lastSequence = $derived(job.events.at(-1)?.sequence ?? 0);

  async function control(action: 'cancel' | 'rerun' | 'reconnect') {
    busy = true;
    error = '';
    status = '';
    try {
      if (action === 'cancel' && cancel) {
        await cancel(job.jobId);
        status = 'Cancellation requested; waiting for a committed terminal event.';
      } else if (action === 'rerun' && rerun) {
        await rerun(job.jobId);
        status = 'Rerun submitted as a new canonical job.';
      } else if (action === 'reconnect' && reconnect) {
        await reconnect(job.jobId, lastSequence);
        status = 'Reconnected; replaying committed events.';
      }
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<article class="panel" aria-labelledby={`job-${job.jobId}`}>
  <header>
    <div>
      <h2 id={`job-${job.jobId}`}>Verification job {job.jobId}</h2>
    </div>
    <strong class="state-label">{job.state.replace('_', ' ')}</strong>
  </header>
  <p>
    Exact work target: <a href={job.workTarget.href}>{job.workTarget.title}</a> · version
    {job.workTarget.revisionId}
  </p>
  {#if job.researchAttempt}<p>
      High-level research attempt: <a href={job.researchAttempt.href}>{job.researchAttempt.title}</a
      >
      · version {job.researchAttempt.revisionId}
    </p>{/if}
  <p>
    {job.purpose.replaceAll('_', ' ')} · exact source version {job.sourceRevisionId} · curated environment
    {job.environment}
  </p>
  <p>{job.evidenceScope}</p>
  <p>
    Entrypoint <code>{job.entrypoint}</code>{#if job.arguments.length}
      · argument vector: <code>{JSON.stringify(job.arguments)}</code>{/if}
  </p>
  <p>Exact input-manifest digest <code>{job.manifestDigest}</code></p>
  <h3>Exact immutable inputs</h3>
  <ul>
    {#each job.inputs as input (`${input.path}:${input.revision?.revisionId ?? input.artifactId}`)}
      <li>
        <code>{input.path}</code> · {input.role} ·
        {#if input.revision}<a href={input.revision.href}>{input.revision.title}</a> · version
          {input.revision.revisionId}{:else}committed artifact {input.artifactId}{/if}
      </li>
    {:else}
      <li>No immutable inputs were returned.</li>
    {/each}
  </ul>
  {#if staleSource}<p class="state-label">
      Historical result: the editor now shows a different source version. This result does not apply
      to unsaved or newer text.
    </p>{/if}
  {#if job.state === 'QUEUED'}<p>
      {job.queuePosition === undefined
        ? 'Queued. No completion estimate is available.'
        : `Canonical queue position ${job.queuePosition}.`}
    </p>{/if}
  {#if connectionInterrupted}<Alert.Root variant="destructive" role="alert">
      Event connection interrupted. Saved editing is unaffected.
      {#if reconnect}<Button
          type="submit"
          variant="outline"
          class=""
          disabled={busy}
          onclick={() => void control('reconnect')}>Reconnect and replay</Button
        >{/if}
    </Alert.Root>{/if}
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status}</p>{/if}

  <h3>Finite limits</h3>
  <dl>
    {#each job.limits as limit (`${limit.label}:${limit.value}`)}<div>
        <dt>{limit.label}</dt>
        <dd>{limit.value}</dd>
      </div>{/each}
  </dl>
  <h3>Committed event history</h3>
  <ol>
    {#each job.events as event (event.id)}<li>
        <strong>#{event.sequence} {event.eventType.replaceAll('_', ' ')}</strong> · {event.createdAt}
        {#if event.attemptId}<span> · controller attempt {event.attemptId}</span>{/if}
      </li>{:else}<li>No committed events.</li>{/each}
  </ol>
  <h3>Controller execution attempts</h3>
  <p class="muted">Controller retries are operational and are not high-level research attempts.</p>
  <ol>
    {#each job.controllerAttempts as attempt (attempt.attemptId)}<li>
        Attempt {attempt.attemptId} · generation {attempt.generation} · {attempt.outcome}
      </li>{:else}<li>No controller attempt recorded.</li>{/each}
  </ol>
  {#if job.resultSummary}<h3>Result for source {job.sourceRevisionId}</h3>
    <p>{job.resultSummary}</p>{/if}
  {#if job.outputs.length}<h3>Committed result artifacts</h3>
    <ul>
      {#each job.outputs as output (`${output.resultId}:${output.artifactId}`)}<li>
          {output.role} <code>{output.path}</code> · artifact {output.artifactId} · sha256:{output.digest}
          · {output.byteLength} bytes
        </li>{/each}
    </ul>{/if}
  <div class="actions">
    {#if canControl && !terminal && cancel}<Button
        type="submit"
        disabled={busy}
        onclick={() => void control('cancel')}>Cancel job</Button
      >{/if}
    {#if canControl && terminal && rerun}<Button
        type="submit"
        disabled={busy || !isolationReady}
        onclick={() => void control('rerun')}>Rerun exact job</Button
      >{#if !isolationReady}<span class="muted"
          >Execution disabled until the Linux isolation gate passes.</span
        >{/if}{/if}
  </div>
</article>

<style>
  article,
  dl {
    display: grid;
    gap: 0.75rem;
  }
  header,
  dl > div,
  .actions {
    display: flex;
    justify-content: space-between;
    align-items: start;
    gap: 1rem;
  }
  h2,
  h3,
  p,
  dl,
  ul,
  ol,
  dd {
    margin-top: 0;
  }
  dd {
    margin-left: 0;
  }
  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }
  @media (max-width: 520px) {
    header,
    dl > div,
    .actions {
      display: grid;
    }
  }
</style>
