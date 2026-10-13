<script lang="ts">
  import ObjectProgress from './ObjectProgress.svelte';
  import ObjectReviews from './ObjectReviews.svelte';
  import ProjectObjectHeading from './ProjectObjectHeading.svelte';
  import type { ResearchObject, PublicResearchObject } from '../lib/research-api';
  import { groupRelationships } from '../lib/relationship-groups';
  import { Link2, X, FileText, ArrowUpRight } from '@lucide/svelte';
  import { Tabs } from 'bits-ui';
  import Markdown from './Markdown.svelte';
  import ProjectRelationships from './ProjectRelationships.svelte';
  import { Button } from '../lib/components/ui/button';
  import {
    attachedObjects,
    diagramObjects,
    versionFormalizations,
    type ProjectMap,
  } from '../lib/project-map';
  let {
    projectId,
    canReview = false,
    data,
    objectId = $bindable(''),
    focusedObject,
    activeTab = $bindable('body'),
    clearable = true,
    pending = false,
    error = '',
    onretry = () => {},
    onfocus = () => {},
  }: {
    projectId: string;
    canReview?: boolean;
    data?: ProjectMap;
    objectId?: string;
    query?: string;
    focusedObject?: Pick<
      ResearchObject | PublicResearchObject,
      'id' | 'kind' | 'current_object_version'
    >;
    activeTab?: string;
    clearable?: boolean;
    pending?: boolean;
    error?: string;
    onretry?: () => void;
    onfocus?: (id: string) => void;
  } = $props();
  const source = $derived(focusedObject ?? data?.objects.find((object) => object.id === objectId));
  let saved = $state<{ base: string; object: ResearchObject }>();
  const focused = $derived(
    saved?.base === source?.current_object_version.id ? saved?.object : source,
  );
  const relationships = $derived(data ? diagramObjects(data) : undefined);
  const notes = $derived(attachedObjects(data, focused?.id ?? objectId, 'NOTE'));
  const attempts = $derived(attachedObjects(data, focused?.id ?? objectId, 'ATTEMPT'));
  const formalizations = $derived(
    versionFormalizations(data, focused?.current_object_version.id ?? ''),
  );
  let selectedNoteId = $state('');
  const selectedNote = $derived(notes.find((note) => note.id === selectedNoteId));
  const contextTabs = $derived([
    { id: 'attempts', label: 'attempt', items: attempts },
    { id: 'notes', label: 'note', items: notes },
    { id: 'formalizations', label: 'formalization', items: formalizations },
  ]);
  const groups = $derived(groupRelationships(relationships, objectId));
  const relationTotal = $derived(groups.reduce((total, group) => total + group.items.length, 0));
  function focus(id: string) {
    objectId = id;
    onfocus(id);
  }
</script>

{#if focused}
  <ProjectObjectHeading
    title={focused.current_object_version.content.title}
    kind={focused.kind}
    number={focused.current_object_version.number}
  >
    {#snippet actions()}
      <Button
        variant="ghost"
        size="icon-sm"
        href={`/projects/${projectId}/objects/${focused.id}`}
        aria-label="Open object"
        title="Open object"><ArrowUpRight size={16} aria-hidden="true" /></Button
      >
      {#if clearable}<Button
          variant="ghost"
          size="icon-sm"
          aria-label="Clear focus"
          title="Clear focus"
          onclick={() => focus('')}><X size={16} aria-hidden="true" /></Button
        >{/if}
    {/snippet}
  </ProjectObjectHeading>{:else}<section class="empty-focus">
    <h2>No object focused</h2>
    <p>Select an object on the map or in the list to see its details and relationships.</p>
  </section>{/if}
{#if focused}
  <Tabs.Root bind:value={activeTab}>
    <Tabs.List class="object-tabs" aria-label="Object information">
      <Tabs.Trigger class="object-tab" value="body"
        ><FileText size={16} aria-hidden="true" />Body</Tabs.Trigger
      >
      <Tabs.Trigger class="object-tab" value="relationships"
        ><Link2 size={16} aria-hidden="true" />Relationships
        {#if data}<span class="relationship-count">{relationTotal}</span>{/if}</Tabs.Trigger
      >
      <Tabs.Trigger class="object-tab" value="attempts"
        >Attempts <span class="relationship-count">{attempts.length}</span></Tabs.Trigger
      >
      <Tabs.Trigger class="object-tab" value="notes"
        >Notes <span class="relationship-count">{notes.length}</span></Tabs.Trigger
      >
      <Tabs.Trigger class="object-tab" value="formalizations"
        >Formalizations <span class="relationship-count">{formalizations.length}</span
        ></Tabs.Trigger
      >
      <Tabs.Trigger class="object-tab" value="progress">Progress</Tabs.Trigger>
      <Tabs.Trigger class="object-tab" value="reviews">Reviews</Tabs.Trigger>
    </Tabs.List>
    <Tabs.Content value="progress">
      <ObjectProgress
        version={focused.current_object_version}
        {projectId}
        canWrite={canReview}
        onsaved={(object) => {
          saved = { base: source!.current_object_version.id, object };
        }}
      />
    </Tabs.Content>
    <Tabs.Content value="body" class="object-body project-inspector-surface">
      {#if focused.current_object_version.content.content_md.trim()}
        <Markdown content={focused.current_object_version.content.content_md} />
      {:else}<p class="muted">No body yet.</p>{/if}
    </Tabs.Content>
    {#each contextTabs as tab (tab.id)}
      <Tabs.Content value={tab.id} class="attached-objects">
        {#if pending}<p role="status">Loading attached objects…</p>
        {:else if error}<p role="alert">{error}</p>
          <Button variant="outline" onclick={onretry}>Retry</Button>
        {:else if tab.id === 'notes'}
          <ul class="note-list" aria-label="Attached notes">
            {#each notes as note (note.id)}
              <li>
                <button
                  class="note-row"
                  class:selected={note.id === selectedNoteId}
                  aria-pressed={note.id === selectedNoteId}
                  onclick={() => (selectedNoteId = note.id)}
                >
                  <FileText size={15} aria-hidden="true" />
                  <span class="note-copy"
                    ><span class="note-title">{note.current_object_version.content.title}</span
                    ><span class="note-excerpt"
                      >{note.current_object_version.content.content_md
                        .replace(/\s+/g, ' ')
                        .slice(0, 100)}</span
                    ></span
                  >
                </button>
              </li>
            {:else}<li class="muted">No notes attached to this object.</li>{/each}
          </ul>
          {#if selectedNote}
            <section class="note-reader project-inspector-surface" aria-label="Selected note">
              <h3>{selectedNote.current_object_version.content.title}</h3>
              <Markdown content={selectedNote.current_object_version.content.content_md} />
              <Button
                variant="ghost"
                size="sm"
                href={`/projects/${projectId}/objects/${selectedNote.id}`}>Open note</Button
              >
            </section>
          {/if}
        {:else}
          {#each tab.items as item (item.id)}
            <details class="attached-object">
              <summary>{item.current_object_version.content.title}</summary>
              {#if tab.id === 'attempts'}
                {@const target = item.current_object_version.structural_relationships.find(
                  (pin) => pin.relationship_type === 'TARGET',
                )}
                {#if target}<p class="muted">
                    <a href={`/projects/${projectId}/records/${target.target_object_version_id}`}
                      >Worked-on version</a
                    >
                  </p>{/if}
              {/if}
              <div class="attached-body">
                <Markdown content={item.current_object_version.content.content_md} />
              </div>
              <Button
                variant="ghost"
                size="sm"
                href={`/projects/${projectId}/objects/${item.id}`}
                target="_blank"
                rel="noopener noreferrer">Open {tab.label}<ArrowUpRight size={14} /></Button
              >
            </details>
          {:else}<p class="muted">
              No {tab.id} attached to this {tab.id === 'formalizations' ? 'version' : 'object'}.
            </p>{/each}
        {/if}
      </Tabs.Content>
    {/each}
    <Tabs.Content value="reviews"
      ><ObjectReviews versionId={focused.current_object_version.id} {canReview} /></Tabs.Content
    >
    <Tabs.Content value="relationships" class="relationships">
      {#if pending}<p class="muted" role="status">Loading relationships…</p>
      {:else if error}<p role="alert">{error}</p>
        <Button variant="outline" onclick={onretry}>Retry relationships</Button>
      {:else}
        <ProjectRelationships {projectId} data={relationships} {objectId} />
      {/if}
    </Tabs.Content>
  </Tabs.Root>
{/if}

<style>
  .note-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 3px;
  }
  .note-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
    padding: 8px;
    text-align: left;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--foreground);
    cursor: pointer;
  }
  .note-row:hover,
  .note-row.selected {
    background: var(--sidebar);
    border-color: var(--sidebar-border);
  }
  .note-row:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 1px;
  }
  .note-row :global(svg) {
    flex-shrink: 0;
    margin-top: 2px;
    color: var(--muted-foreground);
  }
  .note-copy {
    min-width: 0;
    display: grid;
    gap: 2px;
  }
  .note-title {
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .note-excerpt {
    color: var(--muted-foreground);
    font-size: 12px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .note-reader {
    margin-top: 12px;
    padding: 10px;
    font-size: 13px;
  }
  .note-reader h3 {
    font-size: 14px;
    margin: 0 0 8px;
  }

  .attached-object {
    border-bottom: 1px solid var(--border);
    padding: 8px 0;
  }
  .attached-object summary {
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
  }
  .attached-body {
    padding-top: 8px;
    font-size: 13px;
  }

  :global(.object-tabs) {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }
  :global(.object-tab) {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    color: var(--muted-foreground);
    font-size: 13px;
    font-weight: 400;
    cursor: pointer;
  }
  :global(.object-tab[data-state='active']) {
    color: var(--foreground);
    border-bottom-color: var(--brand);
  }
  :global(.object-tab:hover) {
    background: var(--muted);
  }
  :global(.object-tab:focus-visible) {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  :global(.object-body) {
    overflow-wrap: anywhere;
    min-width: 0;
  }
  :global(.object-body .prose) {
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.65;
    color: var(--foreground);
  }
  :global(.object-body .prose p) {
    margin: 10px 0;
  }
  :global(.object-body .prose :is(h1, h2, h3, h4, h5, h6)) {
    font-family: inherit;
    font-weight: 500;
    line-height: 1.4;
    margin: 16px 0 8px;
  }
  :global(.object-body .prose h1) {
    font-size: 18px;
  }
  :global(.object-body .prose h2) {
    font-size: 16px;
  }
  :global(.object-body .prose :is(h3, h4, h5, h6)) {
    font-size: 14px;
  }
  :global(.object-body .prose :is(ul, ol)) {
    margin: 10px 0;
    padding-left: 20px;
  }
  :global(.object-body .prose pre) {
    padding: 10px;
    font-size: 12px;
  }
  :global(.object-body .prose code) {
    font-size: 0.9em;
  }
  :global(.object-body .prose blockquote) {
    margin: 10px 0;
    padding-left: 12px;
    color: var(--muted-foreground);
  }
  :global(.object-body .prose .katex) {
    font-size: 1.05em;
  }
  :global(.object-body .prose .katex-display) {
    margin: 12px 0;
  }
  :global(.object-body .prose > :first-child) {
    margin-top: 0;
  }
  :global(.object-body .prose > :last-child) {
    margin-bottom: 0;
  }
  .relationship-count {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .empty-focus {
    margin: 0 0 12px;
    color: var(--muted-foreground);
    font-size: 14px;
  }
  h2 {
    font-size: 14px;
    font-weight: 400;
  }
</style>
