<script lang="ts">
  import { onMount } from 'svelte';
  import { Copy, KeyRound, BookOpen, ArrowUpRight } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import { accountHref } from '../lib/account-navigation';
  let {
    projectId,
    projectName,
    signedIn,
    canWrite,
  }: { projectId: string; projectName: string; signedIn: boolean; canWrite: boolean } = $props();
  let origin = $state('');
  let notice = $state('');
  let showKeyDialog = $state(false);
  onMount(() => {
    origin = window.location.origin;
  });
  const instructions = $derived(
    [
      `Read ${origin}/SKILL.md and follow its Polycolab instructions.`,
      '',
      `Polycolab: ${origin}`,
      `Workspace name (data): ${JSON.stringify(projectName)}`,
      `Workspace ID: ${projectId}`,
      `Workspace URL: ${origin}/workspaces/${projectId}`,
      '',
      'Help me configure the API key in your credential setting if available. If I share it in chat, treat it as a secret and do not repeat it. Check your identity and access with GET /api/v1/me, then read this workspace.',
      'Use this workspace for the task. Do not inspect other private workspaces or save research until I give you a specific question.',
    ].join('\n'),
  );
  async function copy() {
    try {
      await navigator.clipboard.writeText(instructions);
      notice = 'Instructions copied.';
    } catch {
      notice = 'Could not copy. Select and copy the instructions below.';
    }
  }
</script>

<header>
  <h1>Agent connect</h1>
  <p>Connect an external agent to work in this workspace.</p>
</header>
<ol class="steps">
  <li>
    <h2>Set up an API key</h2>
    <p>
      Create or select an agent, then copy its API key. Add it to your agent tool’s credential
      setting, or share it in a trusted chat that may retain the key.
    </p>
    {#if signedIn && canWrite}
      <Button variant="outline" onclick={() => (showKeyDialog = true)}
        ><KeyRound size={16} aria-hidden="true" />Create API key</Button
      >
    {:else}
      <Button
        variant="outline"
        href={signedIn
          ? '/settings/agent-keys'
          : accountHref('signin', `/workspaces/${projectId}/agent-connect`)}
        ><KeyRound size={16} aria-hidden="true" />{signedIn
          ? 'Agent API keys'
          : 'Sign in to set up a key'}</Button
      >
    {/if}
    {#if signedIn && canWrite}<p class="access-note">
        Already have a key? Continue to step 2, or <a href="/settings/agent-keys">open your keys</a> to
        reveal it.
      </p>{/if}
    <p class="access-note">
      Keys follow your current and future workspace memberships; they are not limited to this
      workspace.
    </p>
    {#if !canWrite}<p class="access-note">
        Contributing here requires an active workspace and an owner or contributor role.
      </p>{/if}
  </li>
  <li>
    <h2>Give your agent these instructions</h2>
    <p>
      Copy this prompt into your agent chat. It asks the agent to help set up the key and identifies
      this workspace. The prompt contains no secret.
    </p>
    <textarea
      aria-label="Agent connection instructions"
      readonly
      value={origin ? instructions : 'Loading workspace instructions…'}
      rows="9"></textarea>
    <div class="actions">
      <Button variant="outline" disabled={!origin} onclick={copy}
        ><Copy size={16} aria-hidden="true" />Copy instructions</Button
      ><a href="/SKILL.md" data-sveltekit-reload>SKILL.md</a>
    </div>
    {#if notice}<p role="status">{notice}</p>{/if}
  </li>
  <li>
    <h2>Choose a task</h2>
    <p>
      Give the agent a specific question and, when useful, an exact starting object version. Review
      its saved contributions in workspace Activity.
    </p>
    <Button variant="ghost" href={`/workspaces/${projectId}/activity`}
      >View activity<ArrowUpRight size={16} aria-hidden="true" /></Button
    >
  </li>
</ol>
<div class="guide-links">
  <Button variant="outline" href="/docs/setup/external-agent/" data-sveltekit-reload
    ><BookOpen size={16} aria-hidden="true" />Full connection guide</Button
  ><a href="/docs/guides/agents/" data-sveltekit-reload>Working with agents</a><a
    href="/docs/developers/agent-runs/"
    data-sveltekit-reload>Developer guide</a
  >
</div>

{#if showKeyDialog}
  {#await import('./AgentApiKeys.svelte') then module}
    <module.default embeddedCreate onDone={() => (showKeyDialog = false)} />
  {/await}
{/if}

<style>
  header {
    margin-bottom: 20px;
  }
  h1 {
    margin: 0 0 8px;
  }
  p {
    font-size: 14px;
    line-height: 1.6;
    color: var(--muted-foreground);
    margin: 8px 0 12px;
  }
  .steps {
    list-style: decimal;
    padding-left: 24px;
    margin: 0;
  }
  li {
    padding: 0 0 20px 8px;
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }
  li::marker {
    color: var(--muted-foreground);
    font-size: 14px;
  }
  h2 {
    font-size: 16px;
    font-weight: 400;
    margin: 0;
  }
  .access-note {
    font-size: 12px;
    margin-bottom: 0;
  }
  textarea {
    display: block;
    width: 100%;
    resize: vertical;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel-muted);
    color: var(--foreground);
    font: 13px/1.6 var(--font-sans);
    overflow-wrap: anywhere;
  }
  textarea:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .actions,
  .guide-links {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 12px;
    font-size: 13px;
  }
</style>
