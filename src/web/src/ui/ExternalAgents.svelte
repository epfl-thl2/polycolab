<script lang="ts">
  import { onMount } from 'svelte';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { AgentIdentity } from '../lib/external-agent-api';
  const { externalAgents } = projectContext();
  let agents = $state<AgentIdentity[]>([]);
  let cursor = $state<string>();
  let error = $state('');
  let busy = $state(false);
  let failedRead: (() => Promise<void>) | undefined;
  async function load(more = false) {
    failedRead = undefined;
    busy = true;
    error = '';
    try {
      const page = await externalAgents.listAgents(more ? cursor : undefined);
      agents = more ? [...agents, ...page.items] : page.items;
      cursor = page.nextCursor;
    } catch (cause) {
      error = explain(cause);
      failedRead = () => load(more);
    } finally {
      busy = false;
    }
  }
  onMount(() => void load());
</script>

<main id="main" class="page" tabindex="-1">
  <h1>External agents</h1>
  <p>
    Manage keys in <a href="/settings/api-keys">Settings → API keys</a>. Agent identities and
    contribution history persist when keys are rotated.
  </p>
  {#if error}<p role="alert">{error}</p>
    <Button onclick={() => failedRead?.()}>Retry</Button>{/if}
  <p>
    <a href="/projects">Open your projects</a> ·
    <a href="/docs/setup/external-agent/" data-sveltekit-reload>Connection guide</a> ·
    <a href="/SKILL.md" data-sveltekit-reload>Read the agent skill (SKILL.md)</a>
  </p>
  <ul class="list">
    {#each agents as agent (agent.id)}<li>
        <a href={`/agent-profiles/${agent.id}`}>{agent.name}</a>
        <form
          onsubmit={async (event) => {
            event.preventDefault();
            busy = true;
            error = '';
            try {
              await externalAgents.renameAgent(agent.id, agent.name);
              await load();
            } catch (cause) {
              error = explain(cause);
            } finally {
              busy = false;
            }
          }}
        >
          <label>Agent name<Input required maxlength={200} bind:value={agent.name} /></label><Button
            type="submit"
            disabled={busy}>Save name</Button
          >
        </form>
      </li>{/each}
  </ul>
  {#if !busy && !agents.length && !error}<p>No agents yet.</p>{/if}
  {#if cursor}<Button disabled={busy} onclick={() => load(true)}>Load more agents</Button>{/if}
</main>
