<script lang="ts">
  import type { Project, ObjectVersion } from '../lib/research-api';
  import type { Activity } from '../lib/history-api';
  import type { ProjectMap } from '../lib/project-map';
  import { canWriteResearch } from '../lib/access';
  import LoadingState from './LoadingState.svelte';
  import ProjectOverview from './ProjectOverview.svelte';
  let {
    project,
    href,
    active,
    onState,
    onCreated,
    onInspect,
    selectedResearch = $bindable(),
    researchCreationOpen = $bindable(false),
    researchCountLabel = $bindable(''),
    selectedActivity = $bindable(),
    mapData = $bindable(),
    mapObjectId = $bindable(''),
    mapPanelTab = $bindable('body'),
  }: {
    project: Project;
    href: string;
    active: boolean;
    onState: (state: { label?: string; dirty: boolean }) => void;
    onCreated: (id: string) => void;
    onInspect: () => void;
    selectedResearch?: { version: ObjectVersion; searchResult: boolean };
    researchCreationOpen?: boolean;
    researchCountLabel?: string;
    selectedActivity?: Activity;
    mapData?: ProjectMap;
    mapObjectId?: string;
    mapPanelTab?: string;
  } = $props();
  const projectId = $derived(project.id);
  const routeUrl = $derived(new URL(href, 'http://project.local'));
  const section = $derived(routeUrl.pathname.split('/')[3] || 'overview');
  const selectedId = $derived(routeUrl.pathname.split('/')[4]);
  $effect(() => {
    if (section === 'map') mapObjectId = routeUrl.searchParams.get('object') ?? '';
  });
  const canWrite = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  const canManage = $derived(project.current_user_role === 'OWNER');
  const canPublish = $derived(canManage && !project.archived_at);
  const member = true;
</script>

{#if section === 'objects' && selectedId}
  {#await import('./Document.svelte')}<LoadingState>
      Opening document…
    </LoadingState>{:then module}{#key selectedId}<module.default
        {projectId}
        objectId={selectedId}
        {canWrite}
        {routeUrl}
        {onState}
      />{/key}{/await}
{:else if section === 'overview' || section === 'research'}
  {#if section === 'overview'}<ProjectOverview
      name={project.name}
      description={project.description}
      visibility={project.visibility}
      role={project.current_user_role}
    />
  {:else}
    {#await import('./ResearchList.svelte')}<LoadingState>
        Loading research…
      </LoadingState>{:then module}<module.default
        {projectId}
        {canWrite}
        publicRead={!member}
        bind:selected={selectedResearch}
        showControls={false}
        bind:showCreation={researchCreationOpen}
        bind:countLabel={researchCountLabel}
        oninspect={onInspect}
      />{/await}{/if}
{:else if section === 'records'}
  {#await import('./ProjectRecords.svelte')}<LoadingState>Loading research…</LoadingState>
  {:then module}{#key selectedId}<module.default
        {projectId}
        {canWrite}
        {canPublish}
        publicRead={!member}
        publicProject={project.visibility === 'PUBLIC'}
        revisionId={selectedId}
      />{/key}{/await}
{:else if section === 'references' && member}
  {#await import('./References.svelte')}<LoadingState>Loading pinned research…</LoadingState>
  {:then module}<module.default {projectId} {canWrite} />{/await}
{:else if section === 'activity'}
  {#await import('./ProjectActivity.svelte')}<LoadingState>Loading activity…</LoadingState>
  {:then module}<module.default
      {projectId}
      publicRead={!member}
      bind:selected={selectedActivity}
      oninspect={() => {
        onInspect();
      }}
    />{/await}
{:else if section === 'map'}
  {#await import('./Graph.svelte')}<LoadingState>
      Loading project map…
    </LoadingState>{:then module}<module.default
      {projectId}
      publicRead={!member}
      bind:objectId={mapObjectId}
      initialFocusId={routeUrl.searchParams.get('object') ?? undefined}
      onfocus={(id) => {
        if (id) onInspect();
      }}
      onreview={(id) => {
        mapObjectId = id;
        if (mapPanelTab !== 'reviews') mapPanelTab = 'reviews';
        onInspect();
      }}
      ondata={(data) => {
        if (mapData !== data) mapData = data;
      }}
    />{/await}
{:else if section === 'sessions'}
  {#if canWrite || project.workspace_mode === 'linear'}{#await import('./Sessions.svelte')}<LoadingState
      >
        Opening private sessions…
      </LoadingState>{:then module}{#key selectedId}<module.default
          {projectId}
          sessionId={selectedId === 'new' ? undefined : selectedId}
          worktreeId={selectedId === 'new'
            ? routeUrl.searchParams.get('worktree') || undefined
            : undefined}
          view={selectedId ? 'chat' : 'list'}
          isVisible={active}
          {onState}
          {onCreated}
        />{/key}{/await}{:else}<h1>Private sessions</h1>
    <p>Agent sessions are available to active contributors and owners.</p>{/if}
{:else if section === 'agent-connect'}
  {#await import('./ProjectAgentConnect.svelte')}<LoadingState
      >Loading connection guide…</LoadingState
    >
  {:then module}<module.default
      {projectId}
      projectName={project.name}
      signedIn={true}
      {canWrite}
    />{/await}
{:else if section === 'proposals'}
  {#if canWrite}{#await import('./Proposals.svelte')}<LoadingState>
        Opening proposal review…
      </LoadingState>{:then module}{#key selectedId}<module.default
          {projectId}
          proposalId={selectedId}
        />{/key}{/await}{:else}<h1>Proposal review unavailable</h1>
    <p>Review requires an active contributor or owner role.</p>{/if}
{:else if section === 'verification' && member}
  {#await import('./VerificationProject.svelte')}<LoadingState>
      Opening verification jobs…
    </LoadingState>{:then module}{#key selectedId}<module.default
        {projectId}
        jobId={selectedId}
        {canWrite}
      />{/key}{/await}
{:else if section === 'settings' && canManage}
  {#await import('./Settings.svelte')}<LoadingState>
      Opening settings…
    </LoadingState>{:then module}<module.default {project} />{/await}
{:else}<h1>Page not found</h1>{/if}
