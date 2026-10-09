<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { onMount } from 'svelte';
  import type { components } from '$lib/api-client';
  import { workspace, explain } from '../svelte-lib/context';
  import { mapPublicationFields, mapPublicPublicationManifest } from '../lib/publication-mappers';
  import PublicationHistory from './PublicationHistory.svelte';

  let { manifestId }: { manifestId: string } = $props();
  const { publication } = workspace();
  let manifest = $state<components['schemas']['PublicPublicationVersionManifestRead']>();
  let error = $state('');

  async function load() {
    error = '';
    try {
      manifest = await publication.publicManifest(manifestId);
    } catch (cause) {
      error = explain(cause);
    }
  }
  onMount(() => void load());
</script>

<main id="main" class="page" tabindex="-1">
  <a href="/commons">← Explore public research</a>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>
    <Button type="submit" onclick={() => void load()}>Retry release</Button>
  {:else if manifest}
    <h1>Immutable public research release</h1>
    <p>
      This is the exact sanitized output confirmed by a human. Publication does not imply catalogue
      admission, endorsement, correspondence, or formal verification.
    </p>
    <PublicationHistory manifests={[mapPublicPublicationManifest(manifest)]} />
    <section class="panel" aria-labelledby="released-fields-heading">
      <h2 id="released-fields-heading">Released public fields</h2>
      <dl>
        {#each mapPublicationFields(manifest.public_fields) as field (`${field.label}:${field.value}`)}
          <div>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        {/each}
      </dl>
    </section>
    {#if manifest.public_fields.artifacts.length}
      <section class="panel" aria-labelledby="released-artifacts-heading">
        <h2 id="released-artifacts-heading">Released artifacts</h2>
        <p>Downloads are untrusted data and are never rendered as active content.</p>
        <ul>
          {#each manifest.public_fields.artifacts as artifact (artifact.id)}
            <li>
              <a href={artifact.content_path} download={`artifact-${artifact.id}`}
                >Download artifact {artifact.id} as data</a
              >
              <span>
                sha256:{artifact.sha256} · {artifact.byte_length.toLocaleString()} bytes ·
                {artifact.media_type}
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else}<LoadingState>Loading immutable public release…</LoadingState>{/if}
</main>

<style>
  section,
  dl,
  ul,
  li {
    display: grid;
    gap: 0.75rem;
  }
  dl > div {
    display: grid;
    grid-template-columns: minmax(8rem, auto) 1fr;
    gap: 0.75rem;
  }
  dd {
    margin: 0;
  }
  ul {
    margin: 0;
    padding-left: 1.25rem;
  }
</style>
