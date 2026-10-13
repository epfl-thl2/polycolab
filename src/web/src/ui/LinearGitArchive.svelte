<script lang="ts">
  import { projectContext, explain } from '../svelte-lib/context';
  import {
    createRepositoryApi,
    decodeFile,
    type RepositoryState,
    type RepositoryCommit,
  } from '../lib/repository-api';
  import { Button } from '../lib/components/ui/button';
  let { projectId }: { projectId: string } = $props();
  const { auth } = projectContext();
  const api = createRepositoryApi({ getAccessToken: auth.token });
  let archive = $state<RepositoryState>();
  let commits = $state<RepositoryCommit[]>([]);
  let content = $state('');
  let error = $state('');
  async function open(branch = 'main') {
    try {
      archive = await api.state(projectId, branch);
      commits = await api.history(projectId, branch);
    } catch (reason) {
      error = explain(reason);
    }
  }
</script>

<details>
  <summary
    onclick={() => {
      if (!archive) void open();
    }}>Git archive · read only</summary
  >
  {#if error}<p role="alert">{error}</p>{/if}
  {#if archive}<p>Preserved at conversion. New changes are in linear history.</p>
    {#each Object.keys(archive.branches ?? {}) as branch (branch)}<Button
        variant="ghost"
        onclick={() => open(branch)}>{branch}</Button
      >{/each}
    {#each archive.files as file (file.path)}<Button
        variant="ghost"
        onclick={async () => {
          try {
            content = decodeFile(
              (await api.file(projectId, archive!.commit!, file.path)).content_base64,
            );
          } catch (reason) {
            error = explain(reason);
          }
        }}>{file.path}</Button
      >{/each}
    <details>
      <summary>Commit history</summary>{#each commits as commit (commit.commit)}<p>
          {commit.message} · {commit.commit.slice(0, 8)}
        </p>{/each}
    </details>
    {#if content}<pre>{content}</pre>{/if}
  {/if}
</details>

<style>
  pre {
    white-space: pre-wrap;
    max-height: 30vh;
    overflow: auto;
    font-size: 0.8rem;
  }
</style>
