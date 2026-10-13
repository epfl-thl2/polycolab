<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { onMount } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import type {
    VerificationEnvironmentRead,
    VerificationJobSubmission,
  } from '../lib/verification-api';

  let { projectId, canWrite }: { projectId: string; canWrite: boolean } = $props();
  const { verification } = projectContext();
  let language = $state<'' | 'LEAN' | 'PYTHON'>('');
  let environments = $state<VerificationEnvironmentRead[]>([]);
  let nextAfter = $state<string | null>(null);
  let environmentId = $state('');
  let pending = $state(true);
  let loadingMore = $state(false);
  let submitting = $state(false);
  let error = $state('');
  let workTargetRevisionId = $state('');
  let researchAttemptRevisionId = $state('');
  let sourceRevisionId = $state('');
  let sourcePath = $state('Main.lean');
  let purpose = $state<VerificationJobSubmission['purpose']>('LEAN_CHECK');
  let evidenceScope = $state('Check the exact saved source against the selected research target.');
  let additionalInputs = $state('');
  let argumentsText = $state('');
  let seed = $state('');
  let limits = $state<VerificationJobSubmission['limits']>();
  let receipt: { body: string; key: string } | undefined;
  let requestGeneration = 0;
  const selected = $derived(environments.find((item) => item.id === environmentId));

  const shortDigest = (value: string) => `${value.slice(0, 12)}…${value.slice(-8)}`;

  async function load(more = false) {
    const request = ++requestGeneration;
    pending = !more;
    loadingMore = more;
    error = '';
    try {
      const page = await verification.environments(projectId, {
        language: language || undefined,
        after: more ? (nextAfter ?? undefined) : undefined,
        limit: 50,
      });
      if (request !== requestGeneration) return;
      environments = more ? [...environments, ...page.items] : page.items;
      nextAfter = page.next_after;
      if (!environments.some((item) => item.id === environmentId)) {
        environmentId = '';
        limits = undefined;
      }
    } catch (cause) {
      if (request === requestGeneration) error = explain(cause);
    } finally {
      if (request === requestGeneration) {
        pending = false;
        loadingMore = false;
      }
    }
  }

  function chooseEnvironment(value: string) {
    environmentId = value;
    const environment = environments.find((item) => item.id === value);
    if (!environment) return;
    limits = { ...environment.limits };
    if (environment.language === 'LEAN') {
      purpose = 'LEAN_CHECK';
      if (sourcePath === 'main.py') sourcePath = 'Main.lean';
    } else {
      if (purpose === 'LEAN_CHECK') purpose = 'PYTHON_RUN';
      if (sourcePath === 'Main.lean') sourcePath = 'main.py';
    }
  }

  function parsedInputs(): VerificationJobSubmission['inputs'] {
    const inputs: VerificationJobSubmission['inputs'] = [
      { path: sourcePath.trim(), role: 'SOURCE', object_version_id: sourceRevisionId.trim() },
    ];
    for (const line of additionalInputs.split('\n').filter((value) => value.trim())) {
      const [role, path, identityKind, identity, ...extra] = line.trim().split(/\s+/);
      if (
        extra.length ||
        !identity ||
        !['INPUT', 'CERTIFICATE'].includes(role) ||
        !['REVISION', 'ARTIFACT'].includes(identityKind)
      )
        throw new Error(
          'Each additional input must be: INPUT|CERTIFICATE path REVISION|ARTIFACT exact-id.',
        );
      inputs.push({
        path,
        role: role as 'INPUT' | 'CERTIFICATE',
        ...(identityKind === 'REVISION'
          ? { object_version_id: identity }
          : { artifact_id: identity }),
      });
    }
    return inputs;
  }

  async function submit() {
    if (!canWrite || !selected || !limits || submitting) return;
    error = '';
    let submission: VerificationJobSubmission;
    try {
      const inputs = parsedInputs();
      if (
        purpose === 'CERTIFICATE_VERIFICATION' &&
        !inputs.some((item) => item.role === 'CERTIFICATE')
      )
        throw new Error('Certificate verification requires an exact certificate input.');
      submission = {
        version: 1,
        project_id: projectId,
        work_target_object_version_id: workTargetRevisionId.trim(),
        research_attempt_object_version_id: researchAttemptRevisionId.trim() || null,
        environment_id: selected.id,
        purpose,
        evidence_scope: evidenceScope.trim(),
        inputs,
        entrypoint: sourcePath.trim(),
        arguments: argumentsText
          .split('\n')
          .map((value) => value.trim())
          .filter(Boolean),
        seed: seed.trim() ? Number(seed) : null,
        limits: { ...limits },
      };
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'The exact input manifest is invalid.';
      return;
    }
    const body = JSON.stringify(submission);
    receipt = receipt?.body === body ? receipt : { body, key: crypto.randomUUID() };
    submitting = true;
    try {
      const job = await verification.submit(projectId, submission, receipt.key);
      receipt = undefined;
      location.assign(`/projects/${projectId}/verification/${job.id}`);
    } catch (cause) {
      error = `${explain(cause)} Your exact IDs and requested limits are retained.`;
    } finally {
      submitting = false;
    }
  }

  onMount(() => {
    void load();
    return () => {
      requestGeneration += 1;
    };
  });
</script>

<section class="panel" aria-labelledby="verification-submit-title">
  <h2 id="verification-submit-title">Submit saved source</h2>
  <p>
    Submission references immutable versions and a curated environment. It does not execute unsaved
    editor text, and environment availability does not imply runner readiness.
  </p>
  <Field.Label
    >Filter environment language<NativeSelect bind:value={language} onchange={() => void load()}
      ><option value="">All languages</option><option value="LEAN">Lean</option><option
        value="PYTHON">Python</option
      ></NativeSelect
    ></Field.Label
  >
  {#if pending}<LoadingState>Loading curated environments…</LoadingState>
  {:else if error && environments.length === 0}<Alert.Root variant="destructive" role="alert"
      >{error}</Alert.Root
    >
    <Button type="button" onclick={() => void load()}>Retry environment discovery</Button>
  {:else if environments.length === 0}<p>No curated environments are currently available.</p>
  {:else}<Field.Label
      >Exact curated environment<NativeSelect
        required
        value={environmentId}
        onchange={(event) => chooseEnvironment(event.currentTarget.value)}
        ><option value="">Choose an environment</option
        >{#each environments as environment (environment.id)}<option value={environment.id}
            >{environment.language} · {environment.toolchain_version} · {environment.id}</option
          >{/each}</NativeSelect
      ></Field.Label
    >
    {#if nextAfter}<Button type="button" disabled={loadingMore} onclick={() => void load(true)}
        >{loadingMore ? 'Loading environments…' : 'Load more environments'}</Button
      >{/if}
  {/if}

  {#if selected}<dl>
      <div>
        <dt>Image digest</dt>
        <dd title={selected.image_digest}>{shortDigest(selected.image_digest)}</dd>
      </div>
      <div>
        <dt>Toolchain</dt>
        <dd>{selected.toolchain_version}</dd>
      </div>
      <div>
        <dt>Dependency lock</dt>
        <dd title={selected.dependency_lock_digest}>
          {shortDigest(selected.dependency_lock_digest)}
        </dd>
      </div>
      <div>
        <dt>Build</dt>
        <dd title={selected.build_digest}>{shortDigest(selected.build_digest)}</dd>
      </div>
      <div>
        <dt>Platform</dt>
        <dd>{selected.platform_identity}</dd>
      </div>
    </dl>
    {#if canWrite && limits}<form
        onsubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
        <Field.Label
          >Exact work-target version ID<Input
            required
            bind:value={workTargetRevisionId}
          /></Field.Label
        >
        <Field.Label
          >Exact research-attempt version ID (optional)<Input
            bind:value={researchAttemptRevisionId}
          /></Field.Label
        >
        <Field.Label
          >Exact saved source version ID<Input
            required
            bind:value={sourceRevisionId}
          /></Field.Label
        >
        <Field.Label
          >Source path and entrypoint<Input
            required
            maxlength={240}
            bind:value={sourcePath}
          /></Field.Label
        >
        <Field.Label
          >Purpose<NativeSelect bind:value={purpose}
            >{#if selected.language === 'LEAN'}<option value="LEAN_CHECK">Lean check</option
              >{:else}<option value="PYTHON_RUN">Python run</option><option
                value="CERTIFICATE_GENERATION">Certificate generation</option
              ><option value="CERTIFICATE_VERIFICATION">Certificate verification</option
              >{/if}</NativeSelect
          ></Field.Label
        >
        <Field.Label
          >Evidence scope<Textarea required maxlength={4000} bind:value={evidenceScope}
          ></Textarea></Field.Label
        >
        <Field.Label
          >Additional exact inputs (optional)<Textarea
            rows={4}
            bind:value={additionalInputs}
            placeholder="INPUT data.json ARTIFACT exact-artifact-id"
          ></Textarea></Field.Label
        >
        <p class="muted">
          One per line: <code>INPUT|CERTIFICATE path REVISION|ARTIFACT exact-id</code>. Paths must
          be relative and normalized.
        </p>
        <Field.Label
          >Arguments (optional; one argv value per line)<Textarea
            rows={3}
            bind:value={argumentsText}
          ></Textarea></Field.Label
        >
        <Field.Label
          >Deterministic seed (optional)<Input
            type="number"
            min="0"
            step="1"
            bind:value={seed}
          /></Field.Label
        >
        <fieldset>
          <legend>Finite requested limits</legend>
          <p class="muted">
            Initialized to this environment's published ceilings. Lower them as needed.
          </p>
          <div class="limits">
            <Field.Label
              >CPU count<Input
                type="number"
                min="1"
                max={selected.limits.cpu_count}
                required
                bind:value={limits.cpu_count}
              /></Field.Label
            >
            <Field.Label
              >CPU seconds<Input
                type="number"
                min="1"
                max={selected.limits.cpu_seconds}
                required
                bind:value={limits.cpu_seconds}
              /></Field.Label
            >
            <Field.Label
              >Wall seconds<Input
                type="number"
                min="1"
                max={selected.limits.wall_seconds}
                required
                bind:value={limits.wall_seconds}
              /></Field.Label
            >
            <Field.Label
              >Memory bytes<Input
                type="number"
                min="16777216"
                max={selected.limits.memory_bytes}
                required
                bind:value={limits.memory_bytes}
              /></Field.Label
            >
            <Field.Label
              >Process count<Input
                type="number"
                min="1"
                max={selected.limits.process_count}
                required
                bind:value={limits.process_count}
              /></Field.Label
            >
            <Field.Label
              >Disk bytes<Input
                type="number"
                min="1048576"
                max={selected.limits.disk_bytes}
                required
                bind:value={limits.disk_bytes}
              /></Field.Label
            >
            <Field.Label
              >Output bytes<Input
                type="number"
                min="0"
                max={selected.limits.output_bytes}
                required
                bind:value={limits.output_bytes}
              /></Field.Label
            >
            <Field.Label
              >Log bytes<Input
                type="number"
                min="0"
                max={selected.limits.log_bytes}
                required
                bind:value={limits.log_bytes}
              /></Field.Label
            >
            <Field.Label
              >Output files<Input
                type="number"
                min="0"
                max={selected.limits.output_files}
                required
                bind:value={limits.output_files}
              /></Field.Label
            >
          </div>
        </fieldset>
        <Button type="submit" disabled={submitting}
          >{submitting ? 'Submitting exact job…' : 'Submit verification job'}</Button
        >
      </form>
    {:else if !canWrite}<p>Write access is required to submit a verification job.</p>{/if}
  {/if}
</section>

<style>
  section,
  form,
  fieldset {
    display: grid;
    gap: 0.75rem;
  }
  dl,
  .limits {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 0.75rem;
  }
  dl div {
    min-width: 0;
  }
  dt {
    font-weight: 700;
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  fieldset {
    border: 1px solid var(--demo-line, #c9cecc);
  }
</style>
