<script lang="ts">
  import { onMount } from 'svelte';
  import { Copy, KeyRound } from '@lucide/svelte';
  import * as Dialog from '../lib/components/ui/dialog';
  import { Button } from '../lib/components/ui/button';
  import { accountHref } from '../lib/account-navigation';

  let {
    open = $bindable(false),
    signedIn,
    trigger,
  }: {
    open?: boolean;
    signedIn: boolean;
    trigger: HTMLButtonElement | null;
  } = $props();
  let origin = $state('');
  let notice = $state('');
  let error = $state('');
  onMount(() => {
    origin = window.location.origin;
  });
  $effect(() => {
    if (!open) {
      notice = '';
      error = '';
    }
  });
  const instructions = $derived(
    [
      `Read ${origin}/SKILL.md and follow its Polycolab instructions.`,
      '',
      `Polycolab: ${origin}`,
      'Help me configure my API key in your private credential setting. Treat the key as a secret and do not repeat it.',
      'Check your identity and access with GET /api/v1/me. Ask me which project and task to work on before reading or changing project files.',
    ].join('\n'),
  );
  async function copy() {
    notice = '';
    error = '';
    try {
      await navigator.clipboard.writeText(instructions);
      notice = 'Instructions copied.';
    } catch {
      error = 'Could not copy. Select and copy the instructions below.';
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="sm:max-w-xl max-h-[calc(100dvh-2rem)] overflow-y-auto p-6"
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      trigger?.focus();
    }}
  >
    <Dialog.Header class="pr-6">
      <Dialog.Title>Onboard your agent</Dialog.Title>
      <Dialog.Description
        >Connect Codex, Claude Code, OpenCode, Pi, or another agent to your project files.</Dialog.Description
      >
    </Dialog.Header>
    <ol class="onboarding-steps">
      <li>
        <h3>Set up an API key</h3>
        <p>
          Create or choose an agent API key in account settings, then add it to your agent’s private
          credential setting.
        </p>
        <Button
          variant="outline"
          href={signedIn ? '/settings/api-keys' : accountHref('signin', '/settings/api-keys')}
        >
          <KeyRound size={15} aria-hidden="true" />{signedIn
            ? 'Open API keys'
            : 'Sign in to set up a key'}
        </Button>
      </li>
      <li>
        <h3>Give your agent these instructions</h3>
        <p>
          Paste this prompt into your agent chat, then tell it which project and task to work on.
        </p>
        <textarea
          aria-label="Agent connection instructions"
          readonly
          rows="7"
          value={origin ? instructions : 'Loading instructions…'}></textarea>
        <div class="copy-actions">
          <Button variant="outline" disabled={!origin} onclick={copy}
            ><Copy size={15} aria-hidden="true" />Copy instructions</Button
          ><a href="/SKILL.md" data-sveltekit-reload>View SKILL.md</a>
        </div>
        {#if error}<p role="alert">{error}</p>{:else if notice}<p role="status">{notice}</p>{/if}
      </li>
    </ol>
    <p class="access-note">
      Keys follow your project memberships. External agents currently work with Basic project files.
    </p>
    <Dialog.Footer
      ><Button variant="outline" href="/docs/setup/external-agent/" data-sveltekit-reload
        >Full connection guide</Button
      ></Dialog.Footer
    >
  </Dialog.Content>
</Dialog.Root>

<style>
  .onboarding-steps {
    list-style: decimal;
    padding-left: 22px;
    margin: 4px 0 0;
  }
  .onboarding-steps li {
    padding-left: 6px;
  }
  .onboarding-steps li + li {
    margin-top: 24px;
  }
  .onboarding-steps li::marker {
    color: var(--muted-foreground);
  }
  h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 500;
  }
  p {
    margin: 8px 0 12px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--muted-foreground);
  }
  textarea {
    display: block;
    width: 100%;
    resize: vertical;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--muted);
    color: var(--foreground);
    font: 12px/1.6 var(--font-sans);
  }
  textarea:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .copy-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 12px;
  }
  .access-note {
    font-size: 12px;
    margin: 0;
  }
</style>
