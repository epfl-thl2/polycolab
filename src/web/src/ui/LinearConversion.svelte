<script lang="ts">
  import { projectContext, explain } from '../svelte-lib/context';
  import { createLinearApi } from '../lib/linear-api';
  import type { Project } from '../lib/research-api';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  let { project }: { project: Project } = $props();
  const { auth, tasks } = projectContext();
  const api = createLinearApi({ getAccessToken: auth.token });
  let trees = $state<{ id: string; title: string }[]>([]);
  let selected = $state('');
  let preview = $state<{ revision: string; files: string[]; saved_changes: boolean }>();
  let receipt = '';
  let error = $state('');
  let busy = $state(false);
  async function act(action: () => Promise<void>) {
    error = '';
    busy = true;
    try {
      await action();
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

{#if project.workspace_mode === 'git' && project.current_user_role === 'OWNER'}
  <section>
    <h2>Switch to linear history</h2>
    <p>
      Choose a saved working copy for live collaboration. Its uncommitted saved files are included.
      The Git branches and working copies remain available as a read-only archive. Finish active
      agent turns and save editor changes before converting.
    </p>
    <Button
      variant="outline"
      disabled={busy}
      onclick={() =>
        act(async () => {
          trees = (await tasks!.list(project.id)).items;
        })}>Choose working copy</Button
    >
    {#if trees.length}<NativeSelect
        bind:value={selected}
        onchange={() => {
          preview = undefined;
        }}
        ><option value="">Select working copy</option>{#each trees as tree (tree.id)}<option
            value={tree.id}>{tree.title}</option
          >{/each}</NativeSelect
      ><Button
        disabled={!selected || busy}
        onclick={() =>
          act(async () => {
            preview = (await api.conversionPreview(project.id, selected)) as typeof preview;
            receipt = crypto.randomUUID();
          })}>Preview conversion</Button
      >{/if}
    {#if preview}<p>
        {preview.files.length} saved files{preview.saved_changes
          ? ', including uncommitted changes'
          : ''}.
      </p>
      <details>
        <summary>Files to include</summary>{#each preview.files as file (file)}<div>
            {file}
          </div>{/each}
      </details>
      <Button
        disabled={busy}
        onclick={() => {
          if (
            confirm(
              'Convert this project to linear history for all members? The selected saved files become the shared workspace. Git becomes read-only.',
            )
          )
            void act(async () => {
              await api.convert(project.id, selected, preview!.revision, receipt);
              location.reload();
            });
        }}>Convert project</Button
      >{/if}
    {#if error}<p role="alert">{error}</p>{/if}
  </section>
{/if}
