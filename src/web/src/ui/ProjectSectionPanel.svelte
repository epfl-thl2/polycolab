<script lang="ts">
  import { onMount } from 'svelte';
  import { X, Globe, LockKeyhole } from '@lucide/svelte';
  import type { Project, ObjectVersion } from '../lib/research-api';
  import { activityView, type Activity } from '../lib/history-api';
  import { deviceSubmissionClock, utcSubmissionClock } from '../lib/submission-time';
  import { Button } from '../lib/components/ui/button';
  import ProjectMapPanel from './ProjectMapPanel.svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { projectContext, explain } from '../svelte-lib/context';
  import { loadProjectMap, type ProjectMap } from '../lib/project-map';
  import { canWriteResearch } from '../lib/access';
  import Markdown from './Markdown.svelte';
  import ProjectObjectHeading from './ProjectObjectHeading.svelte';
  let {
    project,
    section,
    selected = $bindable(),
    selectedResearch = $bindable(),
    mapData,
    mapObjectId = $bindable(''),
    mapPanelTab = $bindable('body'),
  }: {
    project: Project;
    section: string;
    selected?: Activity;
    selectedResearch?: { version: ObjectVersion; searchResult: boolean };
    mapData?: ProjectMap;
    mapObjectId?: string;
    mapPanelTab?: string;
  } = $props();
  const { api } = projectContext();
  const canReview = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  let activeTab = $state('body');
  const previewMap = createQuery(
    toStore(() => ({
      queryKey: ['project-inspector-map', project.id, !project.current_user_role],
      enabled:
        section === 'research' &&
        Boolean(selectedResearch) &&
        ['relationships', 'attempts', 'notes', 'formalizations'].includes(activeTab),
      queryFn: () => loadProjectMap(api, project.id, !project.current_user_role),
    })),
  );
  let clock = $state(utcSubmissionClock);
  onMount(() => {
    clock = deviceSubmissionClock();
  });
  const guidance = $derived(
    (
      {
        'agent-connect': [
          'Agent access',
          'An API key follows your project memberships. Review or revoke keys in account settings. Loading SKILL.md does not grant access.',
        ],
        research: [
          'Research objects',
          'Open an object to read its body, follow its relationships, or review its history.',
        ],
        records: [
          'Research details',
          'Inspect saved revisions, proof details, attempt outcomes, and evidence.',
        ],
        references: [
          'Library imports',
          'Keep published research available alongside this project’s own objects.',
        ],
        sessions: [
          'Private sessions',
          'Agent conversations are private project context. Saved research appears separately in Research objects.',
        ],
        settings: ['Project settings', 'Manage project details, visibility, and access here.'],
      } as Record<string, string[]>
    )[section],
  );
</script>

<div class="project-inspector-surface" class:research-preview={section === 'research'}>
  {#if section === 'map'}
    <ProjectMapPanel
      projectId={project.id}
      {canReview}
      data={mapData}
      bind:objectId={mapObjectId}
      bind:activeTab={mapPanelTab}
    />
  {:else if section === 'research' && selectedResearch}
    {@const version = selectedResearch.version}
    <ProjectMapPanel
      {canReview}
      projectId={project.id}
      objectId={version.object_id}
      focusedObject={{ id: version.object_id, kind: version.kind, current_object_version: version }}
      data={$previewMap.data}
      bind:activeTab
      pending={$previewMap.isPending}
      error={$previewMap.isError ? explain($previewMap.error) : ''}
      onretry={() => $previewMap.refetch()}
      onfocus={(id) => {
        if (!id) selectedResearch = undefined;
        else {
          const object = $previewMap.data?.objects.find((object) => object.id === id);
          if (object)
            selectedResearch = { version: object.current_object_version, searchResult: false };
        }
      }}
    />
  {:else if section === 'research'}
    <p>Select an object to preview its content and version details.</p>
  {:else if section === 'activity' && selected}
    {@const view = activityView(selected)}
    <div class="selection-heading">
      <span>Submission {selected.submission_number ?? '—'}</span><Button
        variant="ghost"
        size="icon-sm"
        aria-label="Clear submission selection"
        onclick={() => (selected = undefined)}><X size={16} aria-hidden="true" /></Button
      >
    </div>
    <ProjectObjectHeading
      title={selected.title}
      kind={selected.object_kind}
      number={selected.object_version_number ?? undefined}
    />
    <dl>
      <dt>Contributor</dt>
      <dd>{view.author}</dd>
      <dt>Change</dt>
      <dd>{view.actionLabel}</dd>
      <dt>Time ({clock.local ? 'local' : 'UTC'})</dt>
      <dd>
        <time datetime={selected.occurred_at} title={clock.timeZone}
          >{clock.format(selected.occurred_at)}</time
        >
      </dd>
    </dl>
    {#if selected.excerpt_md}<Markdown content={selected.excerpt_md} />{/if}
    <Button variant="outline" href={`/projects/${project.id}/records/${selected.object_version_id}`}
      >Open version{selected.object_version_number
        ? ` v${selected.object_version_number}`
        : ''}</Button
    >
  {:else if section === 'activity'}<h2>Submission details</h2>
    <p>Select a change to inspect the change, contributor, and exact revision.</p>
  {:else if section === 'overview'}<h2>Project details</h2>
    <dl>
      <dt>Visibility</dt>
      <dd class="visibility-row">
        <span class="visibility" class:is-private={project.visibility === 'PRIVATE'}>
          {#if project.visibility === 'PUBLIC'}<Globe
              size={14}
              aria-hidden="true"
            />Public{:else}<LockKeyhole size={14} aria-hidden="true" />Private{/if}
        </span><span class="visibility-description">
          · {project.visibility === 'PUBLIC' ? 'Anyone can read' : 'Members only'}</span
        >
      </dd>
      <dt>Your access</dt>
      <dd>
        {project.current_user_role
          ? { OWNER: 'Owner', CONTRIBUTOR: 'Contributor', READ_ONLY: 'Read only' }[
              project.current_user_role
            ]
          : 'Visitor · Read only'}
      </dd>
      {#if project.archived_at}
        <dt>Status</dt>
        <dd>Archived</dd>
      {/if}
    </dl>
  {:else if guidance}<h2>{guidance[0]}</h2>
    <p>{guidance[1]}</p>
    {#if section === 'research' || section === 'records'}<a href={`/projects/${project.id}/map`}
        >Explore connections on the map</a
      >{/if}
  {:else}<h2>Project details</h2>
    <p>Use Navigation to browse research, activity, and the project map.</p>{/if}
</div>

<style>
  .research-preview {
    border: 0;
    box-shadow: none;
    border-radius: 0;
    padding: 0;
    --muted: var(--polycolab-groseille-soft);
  }
  .project-inspector-surface {
    font-family: var(--font-sans);
    font-size: 14px;
    font-weight: 400;
    line-height: 1.65;
  }
  h2 {
    color: var(--muted-foreground);
    font-size: 13px;
    font-weight: 400;
    margin: 0 0 8px;
  }
  p {
    font-size: 14px;
    line-height: 1.65;
    margin: 8px 0 12px;
    color: var(--foreground);
  }
  dl {
    display: grid;
    gap: 2px;
    margin: 8px 0 16px;
    font-size: 14px;
  }
  dt {
    font-size: 12px;
    color: var(--muted-foreground);
    margin-top: 8px;
  }
  dd {
    color: var(--foreground);
    margin: 0;
    overflow-wrap: anywhere;
    text-transform: none;
  }
  .visibility-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0 4px;
  }
  .visibility {
    --visibility-color: var(--research-accent);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: color-mix(in srgb, var(--visibility-color) 70%, var(--muted-foreground));
  }
  .visibility :global(svg) {
    color: var(--visibility-color);
    flex-shrink: 0;
  }
  .visibility.is-private {
    --visibility-color: var(--info);
  }
  .visibility-description {
    color: var(--muted-foreground);
    font-size: inherit;
    line-height: inherit;
  }
  a {
    font-size: 13px;
  }
  .selection-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    margin-bottom: 8px;
    color: var(--muted-foreground);
  }
</style>
