<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import type { RecordRead } from '../lib/records-api';
  import { workspace, explain } from '../svelte-lib/context';
  let { record }: { record: RecordRead } = $props();
  const { catalogue } = workspace();
  let source = $state({ identifier: '', version: '', locator: '' });
  let status = $state('OPEN');
  let reason = $state('');
  let error = $state('');
  let busy = $state(false);
  let saved = $state('');
  let receipt: { body: string; key: string } | undefined;
  async function promote() {
    busy = true;
    error = '';
    const payload = { object_version_id: record.id, source, reported_status: status, reason };
    const body = JSON.stringify(payload);
    if (receipt?.body !== body) receipt = { body, key: crypto.randomUUID() };
    try {
      saved = (await catalogue.promote(payload, receipt.key)).entry_id;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<details class="panel">
  <summary>Human catalogue admission of this supporting statement</summary>
  <p>
    Promotion keeps the statement identity and authorship. It requires a source and does not certify
    correctness.
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if saved}<p role="status">Admitted. <a href={`/commons/${saved}`}>Open catalogue entry</a></p>
  {:else}<form
      onsubmit={(event) => {
        event.preventDefault();
        void promote();
      }}
    >
      <Field.Label
        >Source identifier<Input
          required
          maxlength={2000}
          bind:value={source.identifier}
        /></Field.Label
      >
      <Field.Label
        >Source version<Input required maxlength={500} bind:value={source.version} /></Field.Label
      >
      <Field.Label
        >Source locator<Input required maxlength={1000} bind:value={source.locator} /></Field.Label
      >
      <Field.Label
        >Reported status<Input required maxlength={200} bind:value={status} /></Field.Label
      >
      <Field.Label
        >Admission reason<Textarea required maxlength={4000} bind:value={reason}
        ></Textarea></Field.Label
      >
      <Button type="submit" disabled={busy}>Admit this exact supporting statement</Button>
    </form>{/if}
</details>
