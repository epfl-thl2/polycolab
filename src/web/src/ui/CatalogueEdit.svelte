<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import type { CatalogueEntry, CatalogueRevision } from '../lib/catalogue-api';
  import { workspace, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import FormulationFields from './FormulationFields.svelte';
  let { entry }: { entry: CatalogueEntry } = $props();
  const { catalogue, records } = workspace();
  let draft = $state<CatalogueRevision>();
  let latest = $state<CatalogueEntry>();
  let mode = $state<'SUGGEST' | 'EDIT'>('SUGGEST');
  let busy = $state(false);
  let error = $state('');
  let saved = $state('');
  let receipt: { body: string; key: string } | undefined;
  function start() {
    draft = {
      expected_current_object_version_id: entry.object_version.id,
      title: entry.object_version.content.title,
      content_md: entry.object_version.content.content_md,
      assumptions_md: entry.object_version.content.assumptions_md,
      source: entry.source ? { ...entry.source } : null,
      reported_status: entry.reported_status,
      reason: '',
    };
  }
  async function compare() {
    busy = true;
    error = '';
    try {
      latest = await catalogue.get(entry.entry_id);
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function save() {
    if (!draft) return;
    busy = true;
    error = '';
    const body = JSON.stringify({ mode, draft });
    if (receipt?.body !== body) receipt = { body, key: crypto.randomUUID() };
    try {
      if (mode === 'EDIT') {
        const result = await catalogue.revise(entry.entry_id, draft, receipt.key);
        saved = `/commons/records/${result.object_version_id}`;
      } else {
        const { expected_current_object_version_id, ...suggestion } = draft;
        const result = await records.create(
          {
            destination: {
              kind: 'library',
              statement_object_version_id: expected_current_object_version_id,
            },
            snapshot: {
              kind: 'NOTE',
              content: {
                title: `Suggested correction: ${draft.title}`.slice(0, 500),
                content_md: draft.reason,
                assumptions_md: draft.assumptions_md,
                reported_outcome: 'UNASSESSED',
                explanation_md: null,
              },
              structural_relationships: [
                {
                  relationship_type: 'ATTACHMENT',
                  target_object_version_id: expected_current_object_version_id,
                },
              ],
              change_summary: draft.reason,
            },
            catalogue_suggestion: {
              ...suggestion,
              expected_current_object_version_id: expected_current_object_version_id,
            },
          },
          receipt.key,
        );
        saved = `/commons/records/${result.outputs.find((output) => output.entity_type === 'OBJECT_VERSION')!.entity_id}`;
      }
    } catch (cause) {
      error = `${explain(cause)} Draft retained; compare current saved formulation before changing the base.`;
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel">
  <h2>Formulation changes</h2>
  <p>
    Anyone signed in may suggest a correction. Official edits require the admitting human or a
    moderator; the server checks authority.
  </p>
  {#if !draft}<Button type="submit" onclick={start}>Prepare a formulation change</Button>
  {:else if saved}<p role="status">Saved. <a href={saved}>Read the exact saved version</a></p>
  {:else}
    {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <Field.Label
        >Action<NativeSelect bind:value={mode}
          ><option value="SUGGEST">Suggest a public correction</option><option value="EDIT"
            >Apply an authorized official edit</option
          ></NativeSelect
        ></Field.Label
      >
      <p>Exact base: <code>{draft.expected_current_object_version_id}</code></p>
      <FormulationFields bind:draft />
      <Button type="submit" disabled={busy}
        >{mode === 'EDIT' ? 'Save official version' : 'Submit public suggestion'}</Button
      >
      <Button type="button" disabled={busy} onclick={compare}
        >Reload saved formulation for comparison</Button
      >
    </form>
    {#if latest}
      <h3>Current saved formulation (your draft above is unchanged)</h3>
      <p>{latest.object_version.content.title} · <code>{latest.object_version.id}</code></p>
      <Markdown content={latest.object_version.content.content_md} />
      <h4>Saved assumptions</h4>
      <Markdown content={latest.object_version.content.assumptions_md} />
      <p>
        {#if latest.source}Source: {latest.source.identifier}, {latest.source.version}, {latest
            .source.locator}.{/if}
        Status: {latest.reported_status}
      </p>
      {#if latest.object_version.id !== draft.expected_current_object_version_id}<Button
          type="submit"
          disabled={busy}
          onclick={() => {
            draft!.expected_current_object_version_id = latest!.object_version.id;
          }}>Use this exact base, retaining my edited formulation</Button
        >{/if}
    {/if}
  {/if}
</section>
