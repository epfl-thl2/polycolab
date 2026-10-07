<script lang="ts">
  import { Checkbox } from '../lib/components/ui/checkbox';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { Textarea } from '../lib/components/ui/textarea';
  import { explain } from '../svelte-lib/context';
  import type {
    PublicationConfirmation,
    PublicationManifestView,
    PublicationPreviewView,
    PublicationSelectionDraft,
    PublicationSelectionItem,
  } from '../lib/publication-view';

  let {
    available,
    actorKind,
    canPublish,
    createPreview,
    confirmPublication,
  }: {
    available: PublicationSelectionItem[];
    actorKind: 'HUMAN' | 'AGENT';
    canPublish: boolean;
    createPreview: (
      selection: PublicationSelectionDraft,
      retryKey: string,
    ) => Promise<PublicationPreviewView>;
    confirmPublication: (
      confirmation: PublicationConfirmation,
      retryKey: string,
    ) => Promise<PublicationManifestView>;
  } = $props();

  let selectedIds = $state<string[]>([]);
  let preview = $state<PublicationPreviewView>();
  let confirmed = $state<PublicationManifestView>();
  let reviewed = $state(false);
  let reason = $state('');
  let busy = $state(false);
  let error = $state('');
  let status = $state('');
  let previewReceipt: { body: string; key: string } | undefined;
  let confirmationReceipt: { body: string; key: string } | undefined;

  const authorized = $derived(actorKind === 'HUMAN' && canPublish);
  const confirmable = $derived(
    preview &&
      preview.blockers.length === 0 &&
      preview.artifactBytesReady &&
      reviewed &&
      reason.trim().length > 0,
  );

  function receiptFor(previous: { body: string; key: string } | undefined, body: string) {
    return previous?.body === body ? previous : { body, key: crypto.randomUUID() };
  }

  function select(id: string, checked: boolean) {
    selectedIds = checked
      ? [...new Set([...selectedIds, id])]
      : selectedIds.filter((candidate) => candidate !== id);
    preview = undefined;
    confirmed = undefined;
    reviewed = false;
    confirmationReceipt = undefined;
    error = '';
    status = '';
  }

  async function requestPreview() {
    const selection = { selectedIds: [...selectedIds] };
    const body = JSON.stringify(selection);
    previewReceipt = receiptFor(previewReceipt, body);
    busy = true;
    error = '';
    status = '';
    try {
      preview = await createPreview(selection, previewReceipt.key);
      previewReceipt = undefined;
      confirmationReceipt = undefined;
      reviewed = false;
      status = 'Exact server preview ready. Review it before confirming.';
    } catch (cause) {
      error = `${explain(cause)} Your exact selection is retained.`;
    } finally {
      busy = false;
    }
  }

  async function confirm() {
    if (!preview || !confirmable) return;
    const confirmation = { previewId: preview.previewId, digest: preview.digest, reason };
    const body = JSON.stringify(confirmation);
    confirmationReceipt = receiptFor(confirmationReceipt, body);
    busy = true;
    error = '';
    status = '';
    try {
      confirmed = await confirmPublication(confirmation, confirmationReceipt.key);
      confirmationReceipt = undefined;
      status = 'Publication confirmed from the reviewed exact preview.';
    } catch (cause) {
      const stale =
        typeof cause === 'object' && cause !== null && 'status' in cause && cause.status === 409;
      if (stale) {
        preview = undefined;
        reviewed = false;
        confirmationReceipt = undefined;
      }
      error = `${explain(cause)} Your exact selection is retained.${
        stale ? ' Request and explicitly review a fresh preview.' : ''
      }`;
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel" aria-labelledby="publication-workflow-heading">
  <h2 id="publication-workflow-heading">Selective publication</h2>
  <p>
    Select exact private research. The server computes the authoritative closure and sanitized
    preview. Dedicated human notes, derived summaries, private conversations and internal execution
    events are never selectable here.
  </p>

  {#if !authorized}
    <p class="state-label">
      {actorKind === 'AGENT'
        ? 'Agents cannot publish private research.'
        : 'You do not have publication authority.'}
    </p>
  {:else}
    <fieldset disabled={busy}>
      <legend>Exact publication selection</legend>
      {#each available as item (item.id)}
        <Field.Label>
          <Checkbox
            checked={selectedIds.includes(item.id)}
            onCheckedChange={(checked) => select(item.id, checked)}
          />
          <span>
            <strong>{item.title}</strong>
            <span class="muted">
              · {item.kind}{item.revisionId ? ` · version ${item.revisionId}` : ''}
            </span>
            {#if item.description}<span>{item.description}</span>{/if}
          </span>
        </Field.Label>
      {:else}
        <p>No publishable exact research is available.</p>
      {/each}
    </fieldset>
    <Button
      type="submit"
      disabled={busy || selectedIds.length === 0}
      onclick={() => void requestPreview()}
    >
      Request exact preview
    </Button>
  {/if}

  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if status}<p role="status">{status}</p>{/if}

  {#if preview}
    <section aria-labelledby={`preview-${preview.previewId}`}>
      <h3 id={`preview-${preview.previewId}`}>Exact sanitized public preview</h3>
      <p class="muted">Preview {preview.previewId} · digest {preview.digest}</p>

      <div class="preview-columns">
        <section aria-labelledby="selected-members-heading">
          <h4 id="selected-members-heading">Selected</h4>
          {@render MemberList(preview.selected)}
        </section>
        <section aria-labelledby="required-members-heading">
          <h4 id="required-members-heading">Server-required closure</h4>
          {@render MemberList(preview.required)}
        </section>
        <section aria-labelledby="optional-members-heading">
          <h4 id="optional-members-heading">Optional related links</h4>
          {@render MemberList(preview.optional)}
        </section>
      </div>

      <h4>Public fields</h4>
      <dl>
        {#each preview.publicFields as field (`${field.label}:${field.value}`)}
          <div>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        {/each}
      </dl>

      {#if preview.blockers.length > 0}
        <section aria-labelledby="publication-blockers-heading">
          <h4 id="publication-blockers-heading">Publication blocked</h4>
          <ul>
            {#each preview.blockers as blocker (`${blocker.code}:${blocker.message}`)}
              <li><strong>{blocker.code}:</strong> {blocker.message}</li>
            {/each}
          </ul>
        </section>
      {/if}
      {#if !preview.artifactBytesReady}
        <p class="state-label">Required artifact bytes are not available for publication.</p>
      {/if}

      <Field.Label>
        <Checkbox bind:checked={reviewed} />
        I reviewed this exact server preview and digest.
      </Field.Label>
      <Field.Label>
        Publication reason
        <Textarea required maxlength={4000} bind:value={reason}></Textarea>
      </Field.Label>
      <Button type="submit" disabled={busy || !confirmable} onclick={() => void confirm()}>
        Confirm exact publication
      </Button>
    </section>
  {/if}

  {#if confirmed}
    <p>
      <a href={confirmed.publicHref}>Open immutable public release {confirmed.publicationId}</a>
    </p>
  {/if}
</section>

{#snippet MemberList(members: import('../lib/publication-view').PublicationPreviewMember[])}
  <ul>
    {#each members as member (`${member.kind}:${member.id}`)}
      <li>
        <a href={member.href}>{member.title}</a>
        {#if member.revisionId}<span class="muted"> · version {member.revisionId}</span>{/if}
        {#if member.reason}<span> · {member.reason}</span>{/if}
      </li>
    {:else}
      <li>None.</li>
    {/each}
  </ul>
{/snippet}

<style>
  section,
  fieldset,
  fieldset :global(label),
  fieldset :global(label > span) {
    display: grid;
    gap: 0.75rem;
  }

  fieldset :global(label) {
    grid-template-columns: auto 1fr;
  }

  .preview-columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
    gap: 1rem;
  }

  h2,
  h3,
  h4,
  p,
  ul,
  dl {
    margin-top: 0;
  }

  dl > div {
    display: grid;
    grid-template-columns: minmax(8rem, auto) 1fr;
    gap: 0.75rem;
  }

  dd {
    margin: 0;
  }

  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }
</style>
