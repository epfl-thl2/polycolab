<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  let {
    conclusionRevisionId = $bindable(),
    premiseRevisionIds = $bindable(),
  }: {
    conclusionRevisionId: string;
    premiseRevisionIds: string[];
  } = $props();

  let premiseDraft = $state('');
  let error = $state('');

  function addPremise() {
    const revisionId = premiseDraft.trim();
    if (!revisionId) return;
    if (revisionId === conclusionRevisionId.trim()) {
      error = 'A conclusion cannot also be its own premise.';
      return;
    }
    if (premiseRevisionIds.includes(revisionId)) {
      error = 'That exact premise version is already included.';
      return;
    }
    premiseRevisionIds = [...premiseRevisionIds, revisionId];
    premiseDraft = '';
    error = '';
  }

  function removePremise(revisionId: string) {
    premiseRevisionIds = premiseRevisionIds.filter((candidate) => candidate !== revisionId);
    error = '';
  }
</script>

<fieldset>
  <legend>Proof-sketch structure</legend>
  <p>
    Record one exact conclusion and the ordered, jointly required premise set for this proof sketch.
    Exploratory relationships belong outside this structure.
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  <Field.Label>
    Exact conclusion version ID
    <Input required bind:value={conclusionRevisionId} />
  </Field.Label>
  <div class="premise-entry">
    <Field.Label>
      Exact premise version ID
      <Input bind:value={premiseDraft} />
    </Field.Label>
    <Button type="button" onclick={addPremise}>Add premise</Button>
  </div>
  <h3>Jointly required premises</h3>
  <ol>
    {#each premiseRevisionIds as revisionId (revisionId)}
      <li>
        <code>{revisionId}</code>
        <Button variant="outline" type="button" class="" onclick={() => removePremise(revisionId)}
          >Remove <span class="visually-hidden">premise {revisionId}</span></Button
        >
      </li>
    {:else}
      <li>No premises selected. Add at least one exact premise version.</li>
    {/each}
  </ol>
  <p class="muted">
    Each alternative approach is a separate stable proof sketch with its own premise set. Research
    attempts do not belong to this dependency structure. The server checks access and rejects cyclic
    proof-sketch dependencies.
  </p>
</fieldset>

<style>
  fieldset {
    display: grid;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid var(--demo-line, #c9cecc);
    border-radius: 0.35rem;
  }

  legend,
  h3 {
    font-weight: 700;
  }

  h3,
  p,
  ol {
    margin-top: 0;
  }

  .premise-entry,
  li {
    display: flex;
    align-items: end;
    gap: 0.75rem;
  }

  .premise-entry :global(label) {
    flex: 1;
  }

  li {
    align-items: center;
    justify-content: space-between;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 520px) {
    .premise-entry {
      display: grid;
      align-items: stretch;
    }
  }
</style>
