<script lang="ts">
  import {
    displayRelationships,
    relationshipChoices,
    relationshipWrite,
    type DisplayRelationshipKind,
  } from '../lib/display-relationships';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { onMount } from 'svelte';
  import { workspace, explain } from '../svelte-lib/context';
  import type { ScopedRelationWrite } from '../lib/records-api';
  let {
    revisionId,
    projectId,
    libraryStatementObjectVersionId,
    canWrite,
  }: {
    revisionId: string;
    projectId?: string;
    libraryStatementObjectVersionId?: string;
    canWrite: boolean;
  } = $props();
  const { records, api } = workspace();
  let edges = $state<Awaited<ReturnType<typeof records.relationPage>>['items']>([]);
  let cursor = $state<string | null>(null);
  let busy = $state(false);
  let error = $state('');
  let adding = $state(false);
  let target = $state('');
  let libraryAnchor = $state('');
  let rationale = $state('');
  let kind = $state<DisplayRelationshipKind>('USES');
  let saved = $state(false);
  let proofDirections = $state<Record<string, 'SUPPORTS' | 'REFUTES'>>({});
  const visibleEdges = $derived(
    displayRelationships({
      objects: [],
      relations: edges,
      nodes: Object.entries(proofDirections).map(([id, direction]) => ({
        object_version_id: id,
        object_id: id,
        title: '',
        proof_direction: direction,
      })),
    }),
  );
  let receipt: { body: string; key: string } | undefined;
  const link = (id: string) =>
    projectId ? `/workspaces/${projectId}/records/${id}` : `/commons/records/${id}`;
  async function load(more = false) {
    busy = true;
    error = '';
    try {
      const page = await records.relationPage(
        revisionId,
        more ? (cursor ?? undefined) : undefined,
        projectId,
      );
      edges = more ? [...edges, ...page.items] : page.items;
      cursor = page.next_cursor;
      for (const edge of page.items) {
        if (
          edge.direction === 'UNIDIRECTIONAL' &&
          edge.relationship_type === 'CONCLUSION' &&
          !proofDirections[edge.source_object_version_id]
        ) {
          const proof = await api.getVersion(edge.source_object_version_id);
          if (proof.kind === 'PROOF')
            proofDirections = {
              ...proofDirections,
              [proof.id]: proof.content.direction ?? 'SUPPORTS',
            };
        }
      }
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function save() {
    if (!canWrite || busy) return;
    busy = true;
    error = '';
    const destination = projectId
      ? { kind: 'workspace' as const, workspace_id: projectId }
      : {
          kind: 'library' as const,
          statement_object_version_id: libraryStatementObjectVersionId ?? libraryAnchor.trim(),
        };
    const body: ScopedRelationWrite = {
      destination,
      ...relationshipWrite(kind, revisionId, target.trim()),
      description: rationale || null,
    };
    const serialized = JSON.stringify(body);
    if (receipt?.body !== serialized) receipt = { body: serialized, key: crypto.randomUUID() };
    try {
      await records.relate(body, receipt.key);
      receipt = undefined;
      saved = true;
      adding = false;
      await load();
    } catch (cause) {
      error = `${explain(cause)} Relationship draft retained.`;
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void load();
  });
</script>

<section class="panel">
  <h2>Exact-version relationships</h2>
  <p>
    {projectId
      ? 'Private links may target this workspace or accessible public research. They are not public backlinks.'
      : 'Public links may target only accessible public research.'} A relationship does not establish
    correctness.
  </p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
  {#if saved}<p role="status">Relationship saved.</p>{/if}
  <Button type="submit" disabled={busy} onclick={() => load()}>Reload relationships</Button>
  <ul>
    {#each visibleEdges as edge (edge.id)}<li>
        <a href={link(edge.parentVersionId)}>{edge.parentVersionId}</a>
        → {edge.label}
        <a href={link(edge.childVersionId)}>{edge.childVersionId}</a>
        <p>{edge.originals[0].description}</p>
      </li>{:else}<li>{busy ? 'Loading relationships…' : 'No visible relationships.'}</li>{/each}
  </ul>
  {#if cursor}<Button type="submit" disabled={busy} onclick={() => load(true)}
      >Load more relationships</Button
    >{/if}
  {#if canWrite}<Button
      type="submit"
      disabled={busy}
      onclick={() => {
        adding = !adding;
        saved = false;
      }}>Add exact-version relationship</Button
    >{/if}
  {#if adding && canWrite}<form
      onsubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p>
        Parent version: <code>{revisionId}</code>. This connection stays pinned to the selected
        versions.
      </p>
      {#if !projectId && !libraryStatementObjectVersionId}
        <Field.Label
          >Library statement object-version ID<Input
            required
            bind:value={libraryAnchor}
          /></Field.Label
        >
      {/if}
      <Field.Label
        >Relationship type<NativeSelect bind:value={kind}
          >{#each Object.entries(relationshipChoices) as [value, label] (value)}<option {value}
              >{label}</option
            >{/each}</NativeSelect
        ></Field.Label
      >
      <Field.Label>Exact target version ID<Input required bind:value={target} /></Field.Label>
      <Field.Label
        >Relationship description (optional)<Textarea maxlength={4000} bind:value={rationale}
        ></Textarea></Field.Label
      >
      <Button type="submit" disabled={busy}>Save exact relationship</Button>
    </form>{/if}
</section>
