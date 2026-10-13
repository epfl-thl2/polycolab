<script lang="ts">
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import type { RecordRead } from '../lib/records-api';
  import type { VersionCreate } from '../lib/research-api';
  import { editableVersionSnapshot } from '../lib/version-snapshot';
  import { projectContext, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  let {
    record,
    projectId,
    canWrite = true,
  }: { record: RecordRead; projectId?: string; canWrite?: boolean } = $props();
  const { records, api, query } = projectContext();
  const revisionLink = (revisionId: string) =>
    projectId ? `/projects/${projectId}/records/${revisionId}` : `/commons/records/${revisionId}`;
  let draft = $state<VersionCreate>();
  let versions = $state<RecordRead[]>([]);
  let cursor = $state<string | null>(null);
  let comparison = $state<RecordRead>();
  let busy = $state(false);
  let error = $state('');
  let saved = $state('');
  function start() {
    error = '';
    try {
      draft = {
        expected_current_object_version_id: record.id,
        snapshot: editableVersionSnapshot(record),
      };
    } catch (cause) {
      error = explain(cause);
    }
  }
  async function history(more = false) {
    busy = true;
    error = '';
    try {
      const filters = {
        object_id: record.object_id,
        cursor: more ? (cursor ?? undefined) : undefined,
      };
      const page = projectId
        ? await records.projectList({ ...filters, project_id: projectId })
        : await records.list(filters);
      versions = more ? [...versions, ...page.items] : page.items;
      cursor = page.next_cursor;
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
    try {
      saved = (await api.createVersion(record.object_id, draft)).current_object_version_id;
      if (projectId) {
        await query.invalidateQueries({ queryKey: ['objects', projectId] });
        await query.invalidateQueries({ queryKey: ['records', projectId] });
        await query.invalidateQueries({ queryKey: ['object', projectId, record.object_id] });
      }
    } catch (cause) {
      error = `${explain(cause)} Draft retained. Reload history to compare before choosing a different base.`;
    } finally {
      busy = false;
    }
  }
</script>

<section class="panel">
  <h2>History and editing</h2>
  <p>
    {projectId
      ? 'Project write access and editing permission are checked on every save.'
      : 'Editing requires authorship or moderation authority. Official catalogue formulations use the statement editor instead.'}
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  <Button type="submit" disabled={busy} onclick={() => history()}
    >Reload visible version history</Button
  >
  {#each versions as version (version.id)}
    <p>
      <a href={revisionLink(version.id)}>Version {version.number}: {version.content.title}</a>
      <Button
        type="submit"
        disabled={busy}
        onclick={() => {
          comparison = version;
        }}>Compare this version</Button
      >
    </p>
  {/each}
  {#if cursor}<Button type="submit" disabled={busy} onclick={() => history(true)}
      >Load more versions</Button
    >{/if}
  {#if !draft && canWrite}<Button type="submit" onclick={start}>Edit from this exact version</Button
    >
  {:else if saved}<p role="status">
      Saved. <a href={revisionLink(saved)}>Read saved version</a>
    </p>
  {:else if draft && canWrite}<form
      onsubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p>
        Editing base: <code>{draft.expected_current_object_version_id}</code>. Attachments stay
        pinned to the displayed exact targets.
      </p>
      <Field.Label
        >Title<Input
          required
          maxlength={500}
          bind:value={draft.snapshot.content.title}
        /></Field.Label
      >
      <Field.Label
        >Research<Textarea
          required
          maxlength={100000}
          rows={8}
          bind:value={draft.snapshot.content.content_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Assumptions<Textarea
          required
          maxlength={20000}
          bind:value={draft.snapshot.content.assumptions_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Reported outcome<NativeSelect bind:value={draft.snapshot.content.reported_outcome}>
          {#each ['UNASSESSED', 'IN_PROGRESS', 'FAILED', 'PARTIAL', 'SUCCEEDED'] as outcome (outcome)}<option
              >{outcome}</option
            >{/each}
        </NativeSelect></Field.Label
      >
      <Field.Label
        >Explanation (optional)<Textarea
          maxlength={20000}
          bind:value={draft.snapshot.content.explanation_md}
        ></Textarea></Field.Label
      >
      <Field.Label
        >Change summary<Textarea maxlength={4000} bind:value={draft.snapshot.change_summary}
        ></Textarea></Field.Label
      >
      <Button type="submit" disabled={busy}>Save record version</Button>
    </form>{/if}
  {#if comparison}<h3>Saved version {comparison.number} (draft unchanged)</h3>
    <p>{comparison.content.title} · {comparison.content.reported_outcome}</p>
    <Markdown content={comparison.content.content_md} />
    <h4>Saved assumptions</h4>
    <Markdown content={comparison.content.assumptions_md} />
    {#if comparison.content.explanation_md}<h4>Saved explanation</h4>
      <Markdown content={comparison.content.explanation_md} />{/if}
    {#if draft && comparison.id !== draft.expected_current_object_version_id}
      <Button
        type="submit"
        disabled={busy}
        onclick={() => {
          draft!.expected_current_object_version_id = comparison!.id;
        }}>Use this exact base, retaining my draft</Button
      >
    {/if}
  {/if}
</section>
