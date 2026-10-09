<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { explain } from '../svelte-lib/context';
  import type { ArtifactUploadDraft, ArtifactView } from '../lib/artifact-view';
  import type { ExactResearchRevisionView } from '../lib/research-structure-view';

  let {
    artifacts,
    targets,
    attempts = [],
    maxUploadBytes,
    canUpload = false,
    hasMore = false,
    loadingMore = false,
    onLoadMore,
    upload,
    download,
  }: {
    artifacts: ArtifactView[];
    targets: ExactResearchRevisionView[];
    attempts?: ExactResearchRevisionView[];
    maxUploadBytes: number;
    canUpload?: boolean;
    hasMore?: boolean;
    loadingMore?: boolean;
    onLoadMore?: () => void;
    upload?: (draft: ArtifactUploadDraft) => Promise<unknown>;
    download: (artifactId: string) => Promise<unknown>;
  } = $props();

  let file = $state<File>();
  let role = $state<ArtifactUploadDraft['role']>('EVIDENCE');
  let researchRevisionId = $state('');
  let researchAttemptRevisionId = $state('');
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  async function submit() {
    if (!upload || !file || !researchRevisionId) return;
    if (file.size > maxUploadBytes) {
      error = `File exceeds the ${maxUploadBytes.toLocaleString()} byte upload limit. Your selection is retained.`;
      return;
    }
    const draft: ArtifactUploadDraft = {
      file,
      role,
      researchRevisionId,
      researchAttemptRevisionId: researchAttemptRevisionId || undefined,
    };
    busy = true;
    error = '';
    status = '';
    try {
      await upload(draft);
      file = undefined;
      status = 'Artifact upload and exact attachment committed.';
    } catch (cause) {
      error = `${explain(cause)} Your artifact selection and exact attachment are retained.`;
    } finally {
      busy = false;
    }
  }

  async function requestDownload(artifact: ArtifactView) {
    busy = true;
    error = '';
    status = '';
    try {
      await download(artifact.artifactId);
      status = 'Authorized artifact download started.';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section aria-labelledby="artifacts-heading">
  <h2 id="artifacts-heading">Artifacts</h2>
  <p class="muted">
    Artifacts are untrusted data. A digest identifies bytes but does not grant download access.
  </p>

  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status}</p>{/if}

  {#each artifacts as artifact (artifact.artifactId)}
    <article class="panel" aria-labelledby={`artifact-${artifact.artifactId}`}>
      <header>
        <div>
          <h3 id={`artifact-${artifact.artifactId}`}>Artifact {artifact.artifactId}</h3>
          <p class="muted">{artifact.role}</p>
        </div>
        <strong class="state-label">{artifact.state}</strong>
      </header>
      <dl>
        <div>
          <dt>Digest</dt>
          <dd>{artifact.digest}</dd>
        </div>
        <div>
          <dt>Size</dt>
          <dd>{artifact.byteLength.toLocaleString()} bytes</dd>
        </div>
        <div>
          <dt>Media type</dt>
          <dd>{artifact.mediaType}</dd>
        </div>
        <div>
          <dt>Exact attachment links</dt>
          <dd>{artifact.attachments.length}</dd>
        </div>
        {#each artifact.provenance as field (`${field.label}:${field.value}`)}
          <div>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        {/each}
      </dl>
      <ul class="attachment-list" aria-label={`Exact links for artifact ${artifact.artifactId}`}>
        {#each artifact.attachments as attachment (attachment.attachmentId)}
          <li>
            <strong>{attachment.role}</strong> ·
            <a href={attachment.researchRevision.href}>{attachment.researchRevision.title}</a>
            <span class="muted"> · version {attachment.researchRevision.revisionId}</span>
            {#if attachment.sourceRevision}
              <span>
                · source <a href={attachment.sourceRevision.href}
                  >{attachment.sourceRevision.title}</a
                >
                <span class="muted"> · version {attachment.sourceRevision.revisionId}</span>
              </span>
            {/if}
            {#if attachment.researchAttempt}
              <span>
                · research attempt <a href={attachment.researchAttempt.href}
                  >{attachment.researchAttempt.title}</a
                >
                <span class="muted"> · version {attachment.researchAttempt.revisionId}</span>
              </span>
            {/if}
            <span class="muted"> · attached {attachment.createdAt}</span>
          </li>
        {/each}
      </ul>
      {#if artifact.downloadAvailable}
        <Button type="submit" disabled={busy} onclick={() => void requestDownload(artifact)}>
          Download artifact as data
        </Button>
      {:else}
        <p class="state-label">Artifact bytes are unavailable or not authorized.</p>
      {/if}
    </article>
  {:else}
    <p>No artifacts are visible.</p>
  {/each}

  {#if hasMore && onLoadMore}
    <Button type="submit" variant="outline" class="" disabled={loadingMore} onclick={onLoadMore}>
      {loadingMore ? 'Loading artifacts…' : 'Load more artifacts'}
    </Button>
  {/if}

  {#if canUpload && upload}
    <form
      class="panel"
      onsubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3>Upload artifact</h3>
      <p class="muted">
        Client limit {maxUploadBytes.toLocaleString()} bytes; the deployment may enforce a lower limit.
        Integrity is verified by the server.
      </p>
      <Field.Label>
        File
        <Input
          type="file"
          required
          onchange={(event) => {
            file = event.currentTarget.files?.[0];
            error = '';
          }}
        />
      </Field.Label>
      {#if file}<p class="muted">
          Selected file: {file.name} · {file.size.toLocaleString()} bytes
        </p>{/if}
      <Field.Label>
        Evidence role
        <NativeSelect bind:value={role}>
          <option value="SOURCE">Source</option>
          <option value="INPUT">Input</option>
          <option value="EVIDENCE">Evidence</option>
          <option value="OUTPUT">Output</option>
          <option value="FORMALIZATION">Formalization</option>
          <option value="CERTIFICATE">Certificate</option>
        </NativeSelect>
      </Field.Label>
      <Field.Label>
        Exact research version
        <NativeSelect required bind:value={researchRevisionId}>
          <option value="" disabled>Select an exact version</option>
          {#each targets as target (target.revisionId)}
            <option value={target.revisionId}>{target.title} · {target.revisionId}</option>
          {/each}
        </NativeSelect>
      </Field.Label>
      <Field.Label>
        High-level research attempt (optional)
        <NativeSelect bind:value={researchAttemptRevisionId}>
          <option value="">No research attempt</option>
          {#each attempts as attempt (attempt.revisionId)}
            <option value={attempt.revisionId}>{attempt.title} · {attempt.revisionId}</option>
          {/each}
        </NativeSelect>
      </Field.Label>
      <Button type="submit" disabled={busy || !file || !researchRevisionId}
        >Upload and verify artifact</Button
      >
    </form>
  {/if}
</section>

<style>
  section,
  article,
  form,
  dl {
    display: grid;
    gap: 0.75rem;
  }

  article > header,
  dl > div {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
  }

  h2,
  h3,
  p,
  dl,
  dd {
    margin-top: 0;
  }

  dd {
    margin-left: 0;
    text-align: right;
    overflow-wrap: anywhere;
  }

  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }

  .attachment-list {
    margin: 0;
  }

  .attachment-list li + li {
    margin-top: 0.65rem;
  }

  @media (max-width: 520px) {
    article > header,
    dl > div {
      display: grid;
    }

    dd {
      text-align: left;
    }
  }
</style>
