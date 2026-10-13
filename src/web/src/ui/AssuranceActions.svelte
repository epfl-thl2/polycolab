<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { explain } from '../svelte-lib/context';
  import type {
    CorrespondenceDraft,
    CorrespondenceStatus,
    EndorsementDraft,
  } from '../lib/assurance-view';

  let {
    revisionId,
    projectId,
    statementTargets,
    endorse,
    assessCorrespondence,
  }: {
    revisionId: string;
    projectId?: string;
    statementTargets: Array<{ revisionId: string; title: string }>;
    endorse: (draft: EndorsementDraft, retryKey: string) => Promise<unknown>;
    assessCorrespondence: (draft: CorrespondenceDraft, retryKey: string) => Promise<unknown>;
  } = $props();

  let endorsementActive = $state(true);
  let endorsementRationale = $state('');
  let statementRevisionId = $state('');
  let correspondenceStatus = $state<CorrespondenceStatus>('UNASSESSED');
  let correspondenceRationale = $state('');
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  let endorsementReceipt: { body: string; key: string } | undefined;
  let correspondenceReceipt: { body: string; key: string } | undefined;

  $effect(() => {
    if (!statementTargets.some((target) => target.revisionId === statementRevisionId)) {
      statementRevisionId = statementTargets[0]?.revisionId ?? '';
    }
  });

  function retryKey(
    receipt: { body: string; key: string } | undefined,
    body: string,
  ): { body: string; key: string } {
    return receipt?.body === body ? receipt : { body, key: crypto.randomUUID() };
  }

  async function saveEndorsement() {
    const draft: EndorsementDraft = {
      project_id: projectId,
      object_version_id: revisionId,
      active: endorsementActive,
      rationale: endorsementRationale,
    };
    const body = JSON.stringify(draft);
    endorsementReceipt = retryKey(endorsementReceipt, body);
    busy = true;
    error = '';
    status = '';
    try {
      await endorse(draft, endorsementReceipt.key);
      endorsementReceipt = undefined;
      endorsementRationale = '';
      status = endorsementActive ? 'Endorsement recorded.' : 'Endorsement withdrawn.';
    } catch (cause) {
      error = `${explain(cause)} Endorsement draft retained.`;
    } finally {
      busy = false;
    }
  }

  async function saveCorrespondence() {
    if (!statementRevisionId) return;
    const draft: CorrespondenceDraft = {
      project_id: projectId,
      object_version_id: revisionId,
      statement_object_version_id: statementRevisionId,
      status: correspondenceStatus,
      rationale: correspondenceRationale,
    };
    const body = JSON.stringify(draft);
    correspondenceReceipt = retryKey(correspondenceReceipt, body);
    busy = true;
    error = '';
    status = '';
    try {
      await assessCorrespondence(draft, correspondenceReceipt.key);
      correspondenceReceipt = undefined;
      correspondenceRationale = '';
      status = 'Correspondence assessment recorded.';
    } catch (cause) {
      error = `${explain(cause)} Correspondence draft retained.`;
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel" aria-labelledby={`assurance-actions-${revisionId}`}>
  <h2 id={`assurance-actions-${revisionId}`}>Assess this exact version</h2>
  <p>
    Endorsement and formal/informal correspondence are separate judgments. Neither changes catalogue
    admission or establishes truth.
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status}</p>{/if}

  <form
    onsubmit={(event) => {
      event.preventDefault();
      void saveEndorsement();
    }}
  >
    <fieldset disabled={busy}>
      <legend>Human endorsement</legend>
      <Field.Label>
        Decision
        <NativeSelect bind:value={endorsementActive}>
          <option value={true}>Endorse this version</option>
          <option value={false}>Withdraw my endorsement</option>
        </NativeSelect>
      </Field.Label>
      <Field.Label>
        Endorsement rationale
        <Textarea required maxlength={4000} bind:value={endorsementRationale}></Textarea>
      </Field.Label>
      <Button type="submit">Save endorsement decision</Button>
    </fieldset>
  </form>

  {#if statementTargets.length > 0}
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void saveCorrespondence();
      }}
    >
      <fieldset disabled={busy}>
        <legend>Formal/informal correspondence</legend>
        <Field.Label>
          Exact statement
          <NativeSelect bind:value={statementRevisionId}>
            {#each statementTargets as target (target.revisionId)}
              <option value={target.revisionId}>{target.title} · {target.revisionId}</option>
            {/each}
          </NativeSelect>
        </Field.Label>
        <Field.Label>
          Correspondence assessment
          <NativeSelect bind:value={correspondenceStatus}>
            <option value="MATCHES">Matches</option>
            <option value="PARTIAL">Partial</option>
            <option value="MISMATCH">Mismatch</option>
            <option value="UNASSESSED">Unassessed</option>
          </NativeSelect>
        </Field.Label>
        <Field.Label>
          Correspondence rationale
          <Textarea required maxlength={4000} bind:value={correspondenceRationale}></Textarea>
        </Field.Label>
        <Button type="submit">Save correspondence assessment</Button>
      </fieldset>
    </form>
  {/if}
</section>

<style>
  form + form {
    margin-top: 1.5rem;
  }

  fieldset {
    display: grid;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid var(--demo-line, #c9cecc);
    border-radius: 0.35rem;
  }

  legend {
    padding: 0 0.35rem;
    font-weight: 700;
  }
</style>
