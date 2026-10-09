<script lang="ts">
  import type { ObjectVersion, ResearchObject } from '../lib/research-api';
  import { editableVersionSnapshot } from '../lib/version-snapshot';
  import { objectProgress } from '../lib/object-progress';
  import { workspace, explain } from '../svelte-lib/context';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Textarea } from '../lib/components/ui/textarea';
  import { Button } from '../lib/components/ui/button';
  let {
    version,
    projectId,
    canWrite = false,
    onsaved = () => {},
  }: {
    version: ObjectVersion;
    projectId: string;
    canWrite?: boolean;
    onsaved?: (object: ResearchObject) => void;
  } = $props();
  const { api, query } = workspace();
  const structured = $derived(version.kind === 'PROOF' || version.kind === 'ATTEMPT');
  const current = $derived(
    version.kind === 'PROOF'
      ? version.content.reported_progress
      : version.kind === 'ATTEMPT'
        ? version.content.outcome
        : (version.content.reported_outcome ?? 'UNASSESSED'),
  );
  let value = $state('');
  let explanation = $state('');
  let busy = $state(false);
  let error = $state('');
  $effect(() => {
    value = current ?? '';
    explanation = version.content.explanation_md ?? '';
    error = '';
  });
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !canWrite || value === current) return;
    busy = true;
    error = '';
    try {
      const snapshot = editableVersionSnapshot(version);
      if (snapshot.kind === 'PROOF')
        snapshot.content.reported_progress = value as NonNullable<
          typeof snapshot.content.reported_progress
        >;
      else if (snapshot.kind === 'ATTEMPT')
        snapshot.content.outcome = value as NonNullable<typeof snapshot.content.outcome>;
      else {
        snapshot.content.reported_outcome = value as typeof snapshot.content.reported_outcome;
        if (value === 'FAILED') snapshot.content.explanation_md = explanation;
      }
      snapshot.change_summary = 'Updated reported progress';
      const result = await api.createVersion(version.object_id, {
        expected_current_object_version_id: version.id,
        snapshot,
      });
      query.setQueryData(['object', projectId, version.object_id], result);
      onsaved(result);
      await query.invalidateQueries({
        queryKey: ['workspace-map', projectId],
        refetchType: 'none',
      });
      await Promise.all(
        ['workspace-map', 'workspace-inspector-map', 'objects', 'history'].map((key) =>
          query.invalidateQueries({ queryKey: [key, projectId] }),
        ),
      );
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<form onsubmit={save} aria-label="Reported progress" class="progress-form">
  {#if canWrite}
    <label
      >Reported progress
      <NativeSelect bind:value disabled={busy} aria-label="Reported progress">
        {#if structured}
          <option value="POTENTIAL">Potential</option><option value="PARTIAL">Partial</option
          ><option value="COMPLETE">Complete</option><option value="STALLED">Stalled</option><option
            value="FAILED">Failed</option
          >
        {:else}
          <option value="UNASSESSED">Unassessed</option><option value="IN_PROGRESS"
            >In progress</option
          ><option value="PARTIAL">Partial</option><option value="SUCCEEDED">Complete</option
          ><option value="FAILED">Failed</option>
        {/if}
      </NativeSelect>
    </label>
    {#if !structured && value === 'FAILED'}<label
        >Explanation (optional)<Textarea
          bind:value={explanation}
          maxlength={20000}
          disabled={busy}
        /></label
      >{/if}
    <p class="muted">Saves a new version. This is not a verification result.</p>
    <Button type="submit" size="sm" variant="outline" disabled={busy || value === current}
      >{busy ? 'Saving…' : 'Report progress'}</Button
    >
  {:else}<span class="muted"
      >Reported progress: {objectProgress(version)?.label ?? 'Unassessed'}</span
    >{/if}
  {#if error}<p role="alert">{error}</p>{/if}
</form>

<style>
  .progress-form {
    display: grid;
    gap: 8px;
    margin: 12px 0;
    font-size: 12px;
  }
  label {
    display: grid;
    gap: 4px;
  }
  p {
    margin: 0;
  }
</style>
