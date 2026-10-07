<script lang="ts">
  import * as Field from '../lib/components/ui/field';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Button } from '../lib/components/ui/button';
  import type { CatalogueAdmission } from '../lib/catalogue-api';
  import { workspace, explain } from '../svelte-lib/context';
  let {
    destination = '/library',
    admissionHeading = $bindable(),
  }: {
    destination?: string;
    admissionHeading?: HTMLHeadingElement;
  } = $props();
  const { catalogue } = workspace();
  let busy = $state(false);
  let error = $state('');
  let admissionKey = crypto.randomUUID();
  let admissionPayload = '';
  let admission = $state<
    CatalogueAdmission & { source: NonNullable<CatalogueAdmission['source']> }
  >({
    kind: 'STATEMENT',
    title: '',
    content_md: '',
    assumptions_md: '',
    source: { identifier: '', version: '', locator: '' },
    reported_status: 'Open',
    reason: 'Initial admission',
  });
  async function admit() {
    if (busy) return;
    busy = true;
    error = '';
    try {
      const payload = JSON.stringify(admission);
      if (payload !== admissionPayload) {
        admissionKey = crypto.randomUUID();
        admissionPayload = payload;
      }
      const saved = await catalogue.admit(admission, admissionKey);
      admissionKey = crypto.randomUUID();
      window.location.assign(`${destination}/${saved.entry_id}`);
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel explore-contribution">
  <h2 bind:this={admissionHeading} tabindex="-1">Admit a sourced statement</h2>
  <form
    onsubmit={(event) => {
      event.preventDefault();
      void admit();
    }}
  >
    <Field.Label
      >Statement type<NativeSelect bind:value={admission.kind}
        ><option>STATEMENT</option><option>PROBLEM</option><option>DEFINITION</option></NativeSelect
      ></Field.Label
    >
    <Field.Label>Title<Input required maxlength={500} bind:value={admission.title} /></Field.Label>
    <Field.Label
      >Formulation<Textarea required rows={6} bind:value={admission.content_md}
      ></Textarea></Field.Label
    >
    <Field.Label
      >Assumptions<Textarea required bind:value={admission.assumptions_md}></Textarea></Field.Label
    >
    <Field.Label
      >Source identifier<Input
        required
        bind:value={admission.source.identifier}
        placeholder="DOI, arXiv ID, or stable source"
      /></Field.Label
    >
    <Field.Label>Source version<Input required bind:value={admission.source.version} /></Field.Label
    >
    <Field.Label
      >Source locator<Input
        required
        bind:value={admission.source.locator}
        placeholder="Theorem, section, or page"
      /></Field.Label
    >
    <Field.Label
      >Reported status<Input required bind:value={admission.reported_status} /></Field.Label
    >
    <Field.Label
      >Admission reason<Textarea required bind:value={admission.reason}></Textarea></Field.Label
    >
    <p class="muted">Admission makes this formulation public. It does not establish correctness.</p>
    {#if error}<div class="notice" role="alert">{error}</div>{/if}
    <Button type="submit" disabled={busy}>Admit publicly</Button>
  </form>
</section>
