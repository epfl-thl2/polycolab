<script lang="ts">
  import { Input } from '../lib/components/ui/input';
  import { Checkbox } from '../lib/components/ui/checkbox';
  import { Textarea } from '../lib/components/ui/textarea';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import * as Field from '../lib/components/ui/field';
  import type { CatalogueRevision } from '../lib/catalogue-api';
  let { draft = $bindable() }: { draft: CatalogueRevision } = $props();
</script>

<Field.Label>Title<Input required maxlength={500} bind:value={draft.title} /></Field.Label>
<Field.Label
  >Formulation<Textarea required rows={8} maxlength={100000} bind:value={draft.content_md}
  ></Textarea></Field.Label
>
<Field.Label
  >Assumptions<Textarea required maxlength={20000} bind:value={draft.assumptions_md}
  ></Textarea></Field.Label
>
<Field.Label
  >Recorded status<NativeSelect aria-label="Recorded status" bind:value={draft.reported_status}>
    {#if !['Established', 'Conjectured', 'Open', 'Disproved', 'Definition'].includes(draft.reported_status)}<option
        value={draft.reported_status}>Legacy status: {draft.reported_status}</option
      >{/if}
    {#each ['Established', 'Conjectured', 'Open', 'Disproved', 'Definition'] as status (status)}<option
        >{status}</option
      >{/each}
  </NativeSelect></Field.Label
>
<fieldset>
  <legend>Basis for this status</legend>
  <Field.Label class="row"
    ><Checkbox
      checked={Boolean(draft.source)}
      onCheckedChange={(checked) => {
        draft.source = checked ? { identifier: '', version: '', locator: '' } : null;
      }}
    /> Literature reference</Field.Label
  >
  {#if draft.source}
    <Field.Label
      >Source identifier<Input
        required
        maxlength={2000}
        bind:value={draft.source.identifier}
      /></Field.Label
    >
    <Field.Label
      >Source version<Input
        required
        maxlength={500}
        bind:value={draft.source.version}
      /></Field.Label
    >
    <Field.Label
      >Source locator<Input
        required
        maxlength={1000}
        bind:value={draft.source.locator}
      /></Field.Label
    >
  {/if}
  <Field.Label
    >My human review (required without literature)<Textarea
      required={!draft.source}
      maxlength={4000}
      value={draft.review_rationale ?? ''}
      oninput={(event) => {
        draft.review_rationale = event.currentTarget.value || null;
      }}
      placeholder="Explain how you checked the formulation, assumptions, and reported status."
    ></Textarea></Field.Label
  >
  <p class="muted">
    A review is attributed to you when you submit this version. A citation or review supports the
    recorded status; it is not a machine proof check.
  </p>
</fieldset>
<Field.Label
  >Reason<Textarea required maxlength={4000} bind:value={draft.reason}></Textarea></Field.Label
>
