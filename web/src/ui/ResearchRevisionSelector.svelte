<script lang="ts">
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  export type RevisionChoice = {
    revisionId: string;
    title: string;
    kind: string;
    workspaceName?: string;
    revisionNumber?: number;
  };

  let {
    label,
    value = $bindable(''),
    search,
    required = false,
    help = 'Choose an exact saved version. A later version is never substituted automatically.',
  }: {
    label: string;
    value?: string;
    search: (query: string) => Promise<RevisionChoice[]>;
    required?: boolean;
    help?: string;
  } = $props();

  let query = $state('');
  let results = $state<RevisionChoice[]>([]);
  let selected = $state<RevisionChoice>();
  let busy = $state(false);
  let searched = $state(false);
  let error = $state('');

  async function runSearch() {
    if (busy || query.trim().length < 2) return;
    busy = true;
    error = '';
    searched = true;
    try {
      results = (await search(query.trim())).slice(0, 25);
    } catch {
      error = 'Research versions could not be searched. Please retry.';
    } finally {
      busy = false;
    }
  }

  function choose(choice: RevisionChoice) {
    selected = choice;
    value = choice.revisionId;
  }

  function clear() {
    selected = undefined;
    value = '';
  }
</script>

<fieldset class="revision-selector">
  <legend>{label}{required ? ' (required)' : ''}</legend>
  <p class="muted">{help}</p>
  {#if selected}
    <div class="selected-revision" role="status">
      <span><strong>{selected.title}</strong> · {selected.kind}</span>
      <span>
        {#if selected.workspaceName}{selected.workspaceName} ·
        {/if}{#if selected.revisionNumber}version {selected.revisionNumber} ·
        {/if}<code>{selected.revisionId}</code>
      </span>
      <Button variant="outline" type="button" class="" onclick={clear}>Change selection</Button>
    </div>
  {:else}
    <div class="selector-search">
      <Field.Label>
        Search by title or exact version ID
        <Input
          type="search"
          minlength={2}
          bind:value={query}
          onkeydown={(event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            void runSearch();
          }}
        />
      </Field.Label>
      <Button
        type="button"
        disabled={busy || query.trim().length < 2}
        onclick={() => void runSearch()}>{busy ? 'Searching…' : 'Search'}</Button
      >
    </div>
    {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
    {#if searched && !busy}
      <ul class="selector-results" aria-label={`${label} search results`}>
        {#each results as choice (choice.revisionId)}
          <li>
            <Button
              variant="outline"
              type="button"
              class="selector-choice"
              onclick={() => choose(choice)}
            >
              <span><strong>{choice.title}</strong> · {choice.kind}</span>
              <span>
                {#if choice.workspaceName}{choice.workspaceName} ·
                {/if}{#if choice.revisionNumber}version {choice.revisionNumber} ·
                {/if}<code>{choice.revisionId}</code>
              </span>
            </Button>
          </li>
        {:else}
          <li>No matching accessible versions.</li>
        {/each}
      </ul>
    {/if}
  {/if}
  <Input class="selector-value" aria-label={`${label} exact version ID`} {required} bind:value />
</fieldset>

<style>
  .revision-selector,
  .selector-search,
  .selector-search :global(label),
  .selected-revision,
  :global(.selector-choice) {
    display: grid;
    gap: 0.65rem;
  }
  .revision-selector {
    padding: 1rem;
    border: 1px solid var(--demo-line, #c9cecc);
    border-radius: 0.35rem;
  }
  .selector-search {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
  }
  .selector-results {
    display: grid;
    gap: 0.5rem;
    padding: 0;
    list-style: none;
  }
  :global(.selector-choice) {
    width: 100%;
    justify-items: start;
    text-align: left;
  }
  .selected-revision {
    justify-items: start;
  }
  :global(.selector-value) {
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
  p,
  ul {
    margin-top: 0;
  }
  @media (max-width: 520px) {
    .selector-search {
      grid-template-columns: 1fr;
    }
  }
</style>
