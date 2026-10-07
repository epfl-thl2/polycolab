<script lang="ts">
  import type { PublicationManifestView } from '../lib/publication-view';

  let { manifests }: { manifests: PublicationManifestView[] } = $props();
</script>

<section aria-labelledby="publication-history-heading">
  <h2 id="publication-history-heading">Publication history</h2>
  <p class="muted">
    Each release is immutable. Later private versions remain private and publication does not imply
    catalogue admission.
  </p>
  <ol>
    {#each manifests as manifest (manifest.publicationId)}
      <li class="panel">
        <h3><a href={manifest.publicHref}>Release {manifest.publicationId}</a></h3>
        <p>{manifest.publisher} · {manifest.publishedAt}</p>
        <p class="muted">Exact manifest digest {manifest.digest}</p>
        <details>
          <summary>{manifest.members.length} released members</summary>
          <ul>
            {#each manifest.members as member (`${member.kind}:${member.id}`)}
              <li>
                <a href={member.href}>{member.title}</a>
                {#if member.revisionId}<span class="muted">
                    · version {member.revisionId}</span
                  >{/if}
              </li>
            {/each}
          </ul>
        </details>
      </li>
    {:else}
      <li>No publications recorded.</li>
    {/each}
  </ol>
</section>

<style>
  h2,
  h3,
  p,
  ol,
  ul {
    margin-top: 0;
  }

  ol {
    display: grid;
    gap: 0.75rem;
  }
</style>
