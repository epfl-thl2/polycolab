<script lang="ts">
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import { Badge } from '../lib/components/ui/badge';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { untrack } from 'svelte';
  import type { components } from '$lib/api-client';
  import type {
    PublicComment,
    PublicProject,
    PublicRelation,
    PublicResearchObject,
    ObjectVersion,
  } from '../lib/research-api';
  import { saveArtifactDownload } from '../lib/artifact-api';
  import { explain, workspace } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  import { accountHref } from '../lib/account-navigation';

  let {
    projectId,
    objectId,
    embedded = false,
  }: { projectId?: string; objectId?: string; embedded?: boolean } = $props();
  const { api, artifacts, auth } = workspace();
  let projects = $state<PublicProject[]>([]);
  let project = $state<PublicProject>();
  let objects = $state<PublicResearchObject[]>([]);
  let object = $state<PublicResearchObject>();
  let revisions = $state<ObjectVersion[]>([]);
  let relations = $state<PublicRelation[]>([]);
  let comments = $state<PublicComment[]>([]);
  let attachments = $state<components['schemas']['ArtifactAttachmentItem'][]>([]);
  let projectCursor = $state<string>();
  let objectCursor = $state<string>();
  let revisionCursor = $state<string>();
  let relationCursor = $state<string>();
  let commentCursor = $state<string>();
  let artifactCursor = $state<string | null>();
  let q = $state('');
  let appliedQuery = $state('');
  let busy = $state(false);
  let error = $state('');
  let failedRead: (() => Promise<void>) | undefined;

  async function readMore(action: () => Promise<void>) {
    if (busy) return;
    busy = true;
    error = '';
    failedRead = undefined;
    try {
      await action();
    } catch (cause) {
      error = explain(cause);
      failedRead = action;
    } finally {
      busy = false;
    }
  }

  async function loadProjects(more = false) {
    busy = true;
    error = '';
    failedRead = undefined;
    try {
      const page = await api.listPublicProjects(appliedQuery, more ? projectCursor : undefined);
      projects = more ? [...projects, ...page.items] : page.items;
      projectCursor = page.nextCursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }

  async function loadWorkspace(more = false) {
    if (!projectId) return;
    busy = true;
    error = '';
    failedRead = undefined;
    try {
      if (!project) project = await api.getPublicProject(projectId);
      const page = await api.listObjects(projectId, true, more ? objectCursor : undefined);
      objects = more
        ? [...objects, ...(page.items as PublicResearchObject[])]
        : (page.items as PublicResearchObject[]);
      objectCursor = page.nextCursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }

  async function loadObject() {
    if (!projectId || !objectId) return;
    busy = true;
    error = '';
    failedRead = undefined;
    try {
      const [projectRead, objectRead, revisionPage, relationPage, commentPage, artifactPage] =
        await Promise.all([
          api.getPublicProject(projectId),
          api.getObject(projectId, objectId, true),
          api.listVersions(projectId, objectId, true),
          api.listRelations(projectId, objectId, true),
          api.listPublicComments(projectId, objectId),
          artifacts.publicAttachments(projectId),
        ]);
      project = projectRead;
      object = objectRead as PublicResearchObject;
      revisions = revisionPage.items;
      revisionCursor = revisionPage.nextCursor;
      relations = relationPage.items as PublicRelation[];
      relationCursor = relationPage.nextCursor;
      comments = commentPage.items;
      commentCursor = commentPage.nextCursor;
      attachments = artifactPage.items.filter(
        (attachment) => attachment.object_version_id === object!.current_object_version_id,
      );
      artifactCursor = artifactPage.next_cursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }

  async function moreRevisions() {
    if (!projectId || !objectId || !revisionCursor) return;
    const page = await api.listVersions(projectId, objectId, true, revisionCursor);
    revisions = [...revisions, ...page.items];
    revisionCursor = page.nextCursor;
  }

  async function moreRelations() {
    if (!projectId || !objectId || !relationCursor) return;
    const page = await api.listRelations(projectId, objectId, true, relationCursor);
    relations = [...relations, ...(page.items as PublicRelation[])];
    relationCursor = page.nextCursor;
  }

  async function moreComments() {
    if (!projectId || !objectId || !commentCursor) return;
    const page = await api.listPublicComments(projectId, objectId, commentCursor);
    comments = [...comments, ...page.items];
    commentCursor = page.nextCursor;
  }

  async function moreArtifacts() {
    if (!projectId || !artifactCursor || !object) return;
    const page = await artifacts.publicAttachments(projectId, { cursor: artifactCursor });
    attachments = [
      ...attachments,
      ...page.items.filter((item) => item.object_version_id === object!.current_object_version_id),
    ];
    artifactCursor = page.next_cursor;
  }

  async function download(artifactId: string) {
    const blob = await artifacts.publicDownload(artifactId);
    saveArtifactDownload(blob, artifactId);
  }

  $effect(() => {
    const nextProjectId = projectId;
    const nextObjectId = objectId;
    untrack(() => {
      project = undefined;
      object = undefined;
      objects = [];
      revisions = [];
      relations = [];
      comments = [];
      attachments = [];
      error = '';
      if (nextObjectId) void loadObject();
      else if (nextProjectId) void loadWorkspace();
      else void loadProjects();
    });
  });
</script>

<svelte:head
  ><title
    >{object?.current_object_version.content.title ??
      project?.name ??
      (projectId ? 'Public workspace' : 'Public workspaces')} · Polycolab</title
  ></svelte:head
>

<svelte:element
  this={embedded ? 'div' : 'main'}
  id={embedded ? undefined : 'main'}
  class={embedded ? 'public-workspaces' : 'page discovery-page public-workspaces'}
  tabindex={embedded ? undefined : -1}
>
  {#if !embedded}<nav aria-label="Workspace scope">
      <a href="/workspaces?scope=public" aria-current="page">Public workspaces</a
      >{#if auth.signedIn}<a href="/workspaces?scope=member" aria-current="false">Your workspaces</a
        >{/if}
    </nav>{/if}

  {#if objectId && projectId}
    <p><a href={`/workspaces/${projectId}`}>← {project?.name || 'Public workspace'}</a></p>
    {@render loadError()}
    {#if busy && !object}<LoadingState>Loading exact public research…</LoadingState>
    {:else if object}
      <article aria-labelledby="public-object-title">
        <h1 id="public-object-title">{object.current_object_version.content.title}</h1>
        <div class="public-object-meta">
          <ObjectKindBadge kind={object.kind} /><span>#{object.current_object_version.number}</span>
        </div>
        <p class="muted">
          By {object.current_object_version.authorship.author_display_name ||
            'Researcher'}{#if object.current_object_version.authorship.actor_kind === 'AGENT'}
            · agent-attributed contribution{/if}
        </p>
        <Markdown content={object.current_object_version.content.content_md} />

        <section class="panel">
          <h2>Immutable history</h2>
          <ol class="list">
            {#each revisions as revision (revision.id)}<li>
                <strong>Version {revision.number}: {revision.content.title}</strong>
                <span
                  ><code>{revision.id}</code> · {new Date(
                    revision.created_at,
                  ).toLocaleString()}</span
                >
              </li>{/each}
          </ol>
          {#if revisionCursor}<Button
              type="submit"
              variant="outline"
              class=""
              disabled={busy}
              onclick={() => void readMore(moreRevisions)}>Load more history</Button
            >{/if}
        </section>

        <section class="panel">
          <h2>Exact relationships</h2>
          <ul class="list">
            {#each relations as relation (relation.id)}<li>
                <strong>{relation.relationship_type}</strong>
                <span
                  >{#if relation.direction === 'BIDIRECTIONAL'}
                    <code>{relation.first_object_version_id}</code> ↔
                    <code>{relation.second_object_version_id}</code>
                  {:else}
                    <code>{relation.source_object_version_id}</code> →
                    <code>{relation.target_object_version_id}</code>
                  {/if}</span
                >
                <span>{relation.description}</span>
              </li>{:else}<li>No visible relationships.</li>{/each}
          </ul>
          {#if relationCursor}<Button
              type="submit"
              variant="outline"
              class=""
              disabled={busy}
              onclick={() => void readMore(moreRelations)}>Load more relationships</Button
            >{/if}
        </section>

        <section class="panel">
          <h2>Discussion</h2>
          <ol class="list">
            {#each comments as comment (comment.id)}<li>
                <Markdown content={comment.body_md} />
                <span
                  >{comment.author.display_name || 'Researcher'} · exact version
                  <code>{comment.object_version_id}</code></span
                >
              </li>{:else}<li>No comments.</li>{/each}
          </ol>
          {#if commentCursor}<Button
              type="submit"
              variant="outline"
              class=""
              disabled={busy}
              onclick={() => void readMore(moreComments)}>Load more comments</Button
            >{/if}
        </section>

        <section class="panel">
          <h2>Committed evidence</h2>
          <ul class="list">
            {#each attachments as attachment (attachment.attachment_id)}<li>
                <strong>{attachment.role}</strong>
                <span
                  >{attachment.artifact.media_type} · {attachment.artifact.byte_length} bytes · SHA-256
                  {attachment.artifact.sha256}</span
                >
                <Button
                  type="submit"
                  variant="outline"
                  class=""
                  disabled={busy}
                  onclick={() => void readMore(() => download(attachment.artifact.id))}
                  >Download safely</Button
                >
              </li>{:else}<li>No committed evidence attached to this version.</li>{/each}
          </ul>
          {#if artifactCursor}<Button
              type="submit"
              variant="outline"
              class=""
              disabled={busy}
              onclick={() => void readMore(moreArtifacts)}>Load more evidence</Button
            >{/if}
          <p class="muted">
            An attachment is evidence to inspect; it is not automatically verified.
          </p>
        </section>
      </article>
    {/if}
  {:else if projectId}
    <p><a href="/workspaces?scope=public">← Public workspaces</a></p>
    {#if busy && !project}<LoadingState>Loading public workspace…</LoadingState>
    {:else if !project && error}{@render loadError()}
    {:else if project}
      <header class="discovery-heading">
        <h1>{project.name}</h1>
        <p>{project.description || 'No description provided.'}</p>
        <p class="notice">Saved research is public. Membership controls writing, not reading.</p>
        {#if auth.loaded}<div class="public-workspace-actions">
            <Button
              href={auth.signedIn
                ? `/workspaces/${projectId}`
                : accountHref('signin', `/workspaces/${projectId}`)}
              >{auth.signedIn ? 'Open workspace tools' : 'Sign in to contribute'}</Button
            >
            <span class="muted">Workspace tools require membership.</span>
          </div>{/if}
      </header>
      {@render loadError()}
      <section aria-labelledby="workspace-research-title">
        <h2 id="workspace-research-title">Research</h2>
        <ul class="list">
          {#each objects as item (item.id)}<li>
              <Badge variant="outline">{item.kind}</Badge>
              <a href={`/workspaces/${projectId}/objects/${item.id}`}
                ><strong>{item.current_object_version.content.title}</strong></a
              >
              <span
                >Version {item.current_object_version.number} · {item.current_object_version
                  .authorship.author_display_name || 'Researcher'}</span
              >
            </li>{/each}
        </ul>
        {#if !busy && !error && !objects.length}<DiscoveryState
            level="h3"
            title="No public research yet"
            description="Saved research will appear here when contributors add it."
          />{/if}
        {#if objectCursor}<Button
            type="submit"
            variant="outline"
            class=""
            disabled={busy}
            onclick={() => void loadWorkspace(true)}>Load more research</Button
          >{/if}
      </section>
    {/if}
  {:else}
    <header class="discovery-heading">
      <h1>Public workspaces</h1>
      <p>Read workspace descriptions and saved research without signing in.</p>
      {#if auth.signedIn}<a href="/workspaces">Your workspaces</a>{/if}
    </header>
    <form
      class="toolbar"
      onsubmit={(event) => {
        event.preventDefault();
        appliedQuery = q.trim();
        void loadProjects();
      }}
    >
      <Field.Label class="grow"
        >Search public workspaces<Input type="search" bind:value={q} /></Field.Label
      >
      <Button type="submit" disabled={busy}>Search</Button>
    </form>
    {@render loadError()}
    {#if busy && !projects.length}<LoadingState>Loading public workspaces…</LoadingState>{/if}
    {#if projects.length}<div class="public-workspace-results">
        {#each projects as item (item.id)}<article class="card">
            <h2><a href={`/workspaces/${item.id}`}>{item.name}</a></h2>
            <p>{item.description || 'No description provided.'}</p>
            <small>Updated {new Date(item.updated_at).toLocaleDateString()}</small>
          </article>{/each}
      </div>{/if}
    {#if !busy && !error && !projects.length}<DiscoveryState
        title={appliedQuery ? 'No matching workspaces' : 'No public workspaces yet'}
        description={appliedQuery
          ? 'Try different words or clear your search.'
          : 'Public workspaces will appear here when they are created.'}
      >
        {#if appliedQuery}<Button
            variant="outline"
            onclick={() => {
              q = '';
              appliedQuery = '';
              void loadProjects();
            }}>Clear search</Button
          >{/if}
      </DiscoveryState>{/if}
    {#if projectCursor}<Button
        type="submit"
        variant="outline"
        class=""
        disabled={busy}
        onclick={() => void loadProjects(true)}>Load more workspaces</Button
      >{/if}
  {/if}
</svelte:element>

{#snippet loadError()}
  {#if error}<DiscoveryState
      kind="error"
      title="Could not load public research"
      description={error}
    >
      <Button
        variant="outline"
        disabled={busy}
        onclick={() =>
          failedRead
            ? void readMore(failedRead)
            : objectId
              ? void loadObject()
              : projectId
                ? void loadWorkspace(Boolean(objects.length && objectCursor))
                : void loadProjects(Boolean(projects.length && projectCursor))}>Retry</Button
      >
    </DiscoveryState>{/if}
{/snippet}

<style>
  .public-object-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--muted-foreground);
    margin: 8px 0;
  }
  article,
  section {
    display: grid;
    gap: 1rem;
  }
  .public-workspace-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }
  code,
  span {
    overflow-wrap: anywhere;
  }
</style>
