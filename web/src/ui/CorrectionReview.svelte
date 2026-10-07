<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { onMount } from 'svelte';
  import type { RecordRead } from '../lib/records-api';
  import type { CatalogueRevision } from '../lib/catalogue-api';
  import { workspace, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import FormulationFields from './FormulationFields.svelte';
  let { record }: { record: RecordRead } = $props();
  const { records, auth } = workspace();
  let decision = $state<Awaited<ReturnType<typeof records.decision>>>();
  let edited = $state<CatalogueRevision>();
  let action = $state<'ACCEPT' | 'EDIT_AND_ACCEPT' | 'REJECT'>('ACCEPT');
  let reason = $state('');
  let error = $state('');
  let busy = $state(false);
  let receipt: { body: string; key: string } | undefined;
  onMount(() => {
    if (record.catalogue?.suggestion) {
      const { expected_current_object_version_id, ...formulation } = $state.snapshot(
        record.catalogue.suggestion,
      );
      edited = structuredClone({
        ...formulation,
        expected_current_object_version_id,
      });
    }
    void records
      .decision(record.id)
      .then((value) => {
        decision = value;
      })
      .catch((cause) => {
        if ((cause as { status?: number }).status !== 404) error = explain(cause);
      });
  });
  async function save() {
    busy = true;
    error = '';
    const payload = { action, reason, edited: action === 'EDIT_AND_ACCEPT' ? edited : null };
    const body = JSON.stringify(payload);
    if (receipt?.body !== body) receipt = { body, key: crypto.randomUUID() };
    try {
      decision = await records.decide(record.id, payload, receipt.key);
    } catch (cause) {
      error = `${explain(cause)} Review draft retained. A stale correction cannot be silently rebased; submit a new suggestion against the current formulation.`;
    } finally {
      busy = false;
    }
  }
</script>

{#if record.catalogue?.suggestion}
  <section class="panel">
    <h2>Suggested formulation</h2>
    <p>
      Original target: <a
        href={`/commons/records/${record.catalogue?.suggestion.expected_current_object_version_id}`}
        >{record.catalogue?.suggestion.expected_current_object_version_id}</a
      >
    </p>
    <h3>{record.catalogue?.suggestion.title}</h3>
    <Markdown content={record.catalogue?.suggestion.content_md} />
    <h4>Assumptions</h4>
    <Markdown content={record.catalogue?.suggestion.assumptions_md} />
    <p>
      {#if record.catalogue?.suggestion.source}Source: {record.catalogue?.suggestion.source
          .identifier}, {record.catalogue.suggestion.source.version}, {record.catalogue?.suggestion
          .source.locator}.{/if} Reported status: {record.catalogue.suggestion.reported_status}
    </p>
    {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
    {#if decision}<h3>Human decision: {decision.action}</h3>
      <p>{decision.reason}</p>
      {#if decision.decided_object_version_id}<a
          href={`/commons/records/${decision.decided_object_version_id}`}>Accepted exact version</a
        >{/if}
    {:else if auth.signedIn && edited}
      <h3>Human review</h3>
      <p>
        Only the admitting human or a moderator may decide. The original suggestion remains
        attributable after review.
      </p>
      <form
        onsubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Field.Label
          >Decision<NativeSelect bind:value={action}
            ><option value="ACCEPT">Accept as proposed</option><option value="EDIT_AND_ACCEPT"
              >Edit and accept</option
            ><option value="REJECT">Reject</option></NativeSelect
          ></Field.Label
        >
        {#if action === 'EDIT_AND_ACCEPT'}<FormulationFields bind:draft={edited} />{/if}
        <Field.Label
          >Decision reason<Textarea required maxlength={4000} bind:value={reason}
          ></Textarea></Field.Label
        >
        <Button type="submit" disabled={busy}>Record human decision</Button>
      </form>
    {:else}<p>No visible decision. Sign in to review if authorized.</p>{/if}
  </section>
{/if}
