<script lang="ts">
  import FeedbackToast from './FeedbackToast.svelte';
  import { onMount } from 'svelte';
  import type { components } from '$lib/api-client';
  import type { CatalogueEntry } from '../lib/catalogue-api';
  import { projectContext, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import LibraryBasis from './LibraryBasis.svelte';
  let {
    reference,
    canWrite,
  }: { reference: components['schemas']['ProjectReferenceRead']; canWrite: boolean } = $props();
  const { catalogue } = projectContext();
  let entry = $state<CatalogueEntry>();
  let error = $state('');
  async function load() {
    error = '';
    try {
      entry = await catalogue.revision(reference.object_id, reference.object_version_id);
    } catch (cause) {
      error = explain(cause);
    }
  }
  onMount(() => {
    void load();
  });
  const href = (kind: string) =>
    `/projects/${reference.project_id}/records?import=${reference.object_version_id}&kind=${kind}`;
</script>

<FeedbackToast
  message={error ? 'Library metadata unavailable.' : ''}
  variant="error"
  action={{ label: 'Retry', run: load }}
/>
{#if entry}<LibraryBasis {entry} /><Markdown content={entry.object_version.content.content_md} />
  <details>
    <summary>Assumptions</summary><Markdown content={entry.object_version.content.assumptions_md} />
  </details>{/if}
<FeedbackToast
  message={reference.latest_object_version_id &&
  reference.latest_object_version_id !== reference.object_version_id
    ? 'A newer Library version is available. Your research still uses the imported version.'
    : ''}
  variant="info"
  action={{ label: 'Inspect latest', href: `/library/${reference.object_id}` }}
/>
{#if canWrite}<div class="row">
    <a href={href('ATTEMPT')}>Start attempt</a><a href={href('PROOF')}>Write proof sketch</a><a
      href={href('STATEMENT')}>Develop related claim</a
    >
  </div>{/if}
