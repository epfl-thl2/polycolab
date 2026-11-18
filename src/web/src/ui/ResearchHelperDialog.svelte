<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import { ChevronDown } from '@lucide/svelte';
  import { onDestroy, tick } from 'svelte';
  import { Sparkles, Plus } from '@lucide/svelte';
  import * as Dialog from '../lib/components/ui/dialog';
  import { Button } from '../lib/components/ui/button';
  import { projectContext } from '../svelte-lib/context';
  import { accountHref } from '../lib/account-navigation';
  import { createResearchHelperApi, type ResearchMessage } from '../lib/research-helper-api';
  import { ApiError } from '../lib/projects-api';
  import ChatComposer from './ChatComposer.svelte';
  import Markdown from './Markdown.svelte';

  let {
    open = $bindable(false),
    question,
    onClose,
  }: { open?: boolean; question: string; onClose: () => void } = $props();
  const { auth, capabilities, api: projects } = projectContext();
  const api = createResearchHelperApi({
    getAccessToken: auth.token,
    onUnauthorized: () => auth.expireSession(),
  });
  let selectedModel = $state('');
  const modelCatalog = createQuery(
    toStore(() => ({
      queryKey: ['platform-models'],
      enabled: open && auth.signedIn,
      queryFn: () => projects.listPlatformModels(),
    })),
  );
  const helperModels = $derived(
    ($modelCatalog.data ?? []).filter((model) => model.uses.includes('research_helper')),
  );
  $effect(() => {
    if (!selectedModel && helperModels.length)
      selectedModel =
        helperModels.find((model) => model.default_for.includes('research_helper'))?.catalog_id ??
        helperModels[0].catalog_id;
  });
  let messages = $state<ResearchMessage[]>([]);
  let message = $state('');
  let pending = $state('');
  let busy = $state(false);
  let error = $state('');
  let transcript = $state<HTMLDivElement>();
  let controller: AbortController | undefined;
  $effect(() => {
    if (open) message = question;
  });
  onDestroy(() => controller?.abort());
  const available = $derived(capabilities?.enabled('research_helper') ?? false);
  const full = $derived(
    messages.length >= 30 ||
      new TextEncoder().encode(messages.map((item) => item.content).join('') + message).length >
        48_000,
  );
  async function send(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !available || !auth.signedIn || !message.trim() || full) return;
    pending = message.trim();
    busy = true;
    error = '';
    const next: ResearchMessage[] = [...messages, { role: 'user', content: pending }];
    controller = new AbortController();
    try {
      const response = await api.ask(next, controller.signal, selectedModel);
      messages = [...next, { role: 'assistant', content: response.content }];
      if (message.trim() === pending) message = '';
      await tick();
      transcript?.scrollTo({ top: transcript.scrollHeight, behavior: 'smooth' });
    } catch (cause) {
      if (controller.signal.aborted) return;
      error =
        cause instanceof ApiError && cause.status === 429
          ? 'The assistant is busy. Wait a minute before trying again.'
          : cause instanceof ApiError && cause.status === 503
            ? 'The research assistant is not available yet.'
            : 'Could not get a response. Your question is still here; try again.';
    } finally {
      busy = false;
      pending = '';
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="sm:max-w-2xl max-h-[calc(100dvh-2rem)] overflow-y-auto p-6"
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      onClose();
    }}
  >
    <Dialog.Header class="pr-6"
      ><Dialog.Title
        ><span class="helper-title"
          ><Sparkles size={18} aria-hidden="true" />Research assistant</span
        ></Dialog.Title
      ><Dialog.Description
        >Explore questions, compare approaches, and plan your research.</Dialog.Description
      ></Dialog.Header
    >
    {#if !auth.signedIn}<p>Sign in to use the platform’s research assistant.</p>
      <Button href={accountHref('signin', '/')}>Sign in</Button>
    {:else if capabilities?.loading}<p role="status">Checking availability…</p>
    {:else if !available}<p role="status">The research assistant is not available yet.</p>
    {:else}
      <div class="helper-toolbar">
        <span>No project required</span><Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onclick={() => {
            messages = [];
            message = '';
            error = '';
          }}><Plus size={14} aria-hidden="true" />New chat</Button
        >
      </div>
      <div
        class="helper-transcript"
        bind:this={transcript}
        role="log"
        aria-label="Research chat"
        aria-live="polite"
      >
        {#if !messages.length && !busy}<p class="helper-welcome">
            What would you like to investigate? Share a question, an idea, or material you want to
            work through.
          </p>{/if}
        {#each messages as item, index (index)}<article class:user={item.role === 'user'}>
            <h3>{item.role === 'user' ? 'You' : 'Research assistant'}</h3>
            <Markdown content={item.content} />
          </article>{/each}
        {#if busy}<article class="user">
            <h3>You</h3>
            <p>{pending}</p>
          </article>
          <p role="status">Thinking…</p>{/if}
      </div>
      {#if error}<p role="alert" class="helper-error">{error}</p>{/if}
      {#if full}<p role="status">
          This chat has reached its length limit. Start a new chat to continue.
        </p>{/if}
      <ChatComposer
        bind:value={message}
        onsubmit={send}
        disabled={busy || full}
        inputDisabled={busy}
        maxlength={8000}
        placeholder="Ask a research question…"
      >
        {#snippet preset()}
          {#if helperModels.length}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger
                class="chat-model-trigger"
                disabled={busy}
                aria-label="Choose research model"
              >
                {helperModels.find((model) => model.catalog_id === selectedModel)?.display_name ??
                  'Choose model'}<ChevronDown class="size-3" />
              </DropdownMenu.Trigger>
              <DropdownMenu.Content side="top" align="end">
                <DropdownMenu.Label>Polycolab models</DropdownMenu.Label>
                <DropdownMenu.RadioGroup bind:value={selectedModel}>
                  {#each helperModels as model (model.id)}
                    <DropdownMenu.RadioItem value={model.catalog_id}
                      >{model.display_name}</DropdownMenu.RadioItem
                    >
                  {/each}
                </DropdownMenu.RadioGroup>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {/if}
        {/snippet}
      </ChatComposer>
      <p class="helper-note">
        This chat isn’t saved to your history. The assistant has no access to project files or live
        web search.
      </p>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<style>
  .helper-title {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .helper-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .helper-transcript {
    max-height: 45dvh;
    overflow-y: auto;
    min-height: 120px;
    overflow-wrap: anywhere;
  }
  article {
    padding: 14px 12px;
    border-radius: 8px;
    margin: 8px 0;
  }
  article.user {
    background: var(--muted);
  }
  h3 {
    margin: 0 0 8px;
    font-size: 12px;
    font-weight: 500;
  }
  p {
    font-size: 13px;
    line-height: 1.6;
    margin: 8px 0;
  }
  .helper-welcome {
    color: var(--muted-foreground);
    padding: 12px;
  }
  .helper-note {
    font-size: 11px;
    color: var(--muted-foreground);
    margin: 0;
  }
  .helper-error {
    color: var(--destructive);
  }
</style>
