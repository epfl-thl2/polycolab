<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  import { workspace, explain } from '../svelte-lib/context';
  const { records, catalogue } = workspace();
  let kind = $state<'RECORD' | 'CATALOGUE'>('RECORD');
  let objectId = $state('');
  let base = $state('');
  let action = $state<'HIDE' | 'RESTORE'>('HIDE');
  let reason = $state('');
  let busy = $state(false);
  let error = $state('');
  let saved = $state('');
  let receipt: { body: string; key: string } | undefined;
  async function save() {
    busy = true;
    error = '';
    saved = '';
    const body = JSON.stringify({ kind, objectId, base, action, reason });
    if (receipt?.body !== body) receipt = { body, key: crypto.randomUUID() };
    try {
      if (kind === 'RECORD')
        await records.moderate(
          objectId.trim(),
          { expected_current_object_version_id: base.trim(), hidden: action === 'HIDE', reason },
          receipt.key,
        );
      else
        await catalogue.moderate(
          objectId.trim(),
          { expected_current_object_version_id: base.trim(), action, reason },
          receipt.key,
        );
      saved = `${action === 'HIDE' ? 'Hidden' : 'Restored'} with an immutable moderation reason.`;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<main id="main" class="page narrow" tabindex="-1">
  <h1>Public research moderation</h1>
  <p>
    Only assigned human moderators may hide or restore research. Workspace ownership does not grant
    moderation rights. Public content is unavailable while hidden; restoration uses the known object
    and exact current version IDs.
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">
      {error} Inputs are retained; verify the exact saved version before retrying.
    </Alert.Root>{/if}
  {#if saved}<p role="status">{saved}</p>{/if}
  <form
    class="panel"
    onsubmit={(event) => {
      event.preventDefault();
      void save();
    }}
  >
    <Field.Label
      >Resource<NativeSelect bind:value={kind}
        ><option value="RECORD">Public research object</option><option value="CATALOGUE"
          >Catalogue entry</option
        ></NativeSelect
      ></Field.Label
    >
    <Field.Label>Object or catalogue entry ID<Input required bind:value={objectId} /></Field.Label>
    <Field.Label>Exact current version ID<Input required bind:value={base} /></Field.Label>
    <Field.Label
      >Action<NativeSelect bind:value={action}
        ><option>HIDE</option><option>RESTORE</option></NativeSelect
      ></Field.Label
    >
    <Field.Label
      >Reason<Textarea required maxlength={4000} bind:value={reason}></Textarea></Field.Label
    >
    <Button type="submit" disabled={busy}>Apply moderation</Button>
  </form>
</main>
