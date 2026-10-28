<script lang="ts">
  import { tick, type Snippet } from 'svelte';
  import { ArrowUp, Square, LoaderCircle } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import { Textarea } from '../lib/components/ui/textarea';

  let {
    value = $bindable(''),
    label = 'Message',
    placeholder = 'Ask a question or describe what you want to do…',
    disabled = false,
    inputDisabled = false,
    sendReason = '',
    submitLabel = 'Send message',
    maxlength = 100000,
    prompts = [],
    configuration,
    preset,
    contextControls,
    onsubmit,
    onstop,
    stopping = false,
    stopDisabled = false,
  }: {
    value?: string;
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    inputDisabled?: boolean;
    sendReason?: string;
    submitLabel?: string;
    maxlength?: number;
    prompts?: string[];
    configuration?: Snippet;
    preset?: Snippet;
    contextControls?: Snippet;
    onsubmit: (event: SubmitEvent) => void | Promise<void>;
    onstop?: () => void | Promise<void>;
    stopping?: boolean;
    stopDisabled?: boolean;
  } = $props();
  let input = $state<HTMLTextAreaElement | null>(null);
  $effect(() => {
    void value;
    void tick().then(() => {
      if (!input) return;
      input.style.height = '';
      if (input.scrollHeight > input.clientHeight)
        input.style.height = `${Math.min(input.scrollHeight, 240)}px`;
    });
  });
  function keydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (event.repeat || disabled || onstop) return;
    const form = (event.currentTarget as HTMLTextAreaElement).form;
    const submit = form?.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (submit && !submit.disabled) form?.requestSubmit(submit);
  }
  async function choosePrompt(prompt: string) {
    value = prompt;
    await tick();
    input?.focus();
  }
</script>

<div class="project-chat-start-group">
  <form
    class="project-chat-start"
    onsubmit={(event) => {
      if (onstop) {
        event.preventDefault();
        return;
      }
      return onsubmit(event);
    }}
  >
    {#if configuration}<div class="project-chat-config-bar" aria-label="Chat configuration">
        {@render configuration()}
      </div>{/if}
    <div class="project-chat-composer-surface">
      <Textarea
        required
        {maxlength}
        aria-label={label}
        {placeholder}
        bind:value
        bind:ref={input}
        disabled={inputDisabled}
        onkeydown={keydown}
      />
      {#if contextControls}{@render contextControls()}{/if}
      <div class="project-chat-start-footer">
        {#if sendReason}<span class="project-chat-send-reason" role="status">{sendReason}</span
          >{/if}
        {#if preset}<div class="project-chat-composer-preset">{@render preset()}</div>{/if}
        {#if onstop}
          <Button
            type="button"
            size="icon"
            class="project-chat-send"
            aria-label={stopping ? 'Stopping agent' : 'Stop agent'}
            title={stopping ? 'Stopping agent…' : 'Stop agent'}
            disabled={stopping || stopDisabled}
            onclick={onstop}
          >
            {#if stopping}<LoaderCircle
                class="size-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            {:else}<Square class="size-3" fill="currentColor" aria-hidden="true" />{/if}
          </Button>
        {:else}
          <Button
            type="submit"
            size="icon"
            class="project-chat-send"
            aria-label={submitLabel}
            title={submitLabel}
            {disabled}><ArrowUp class="size-4" aria-hidden="true" /></Button
          >
        {/if}
      </div>
    </div>
  </form>
  {#if prompts.length}<div class="project-chat-prompt-starters" aria-label="Suggested prompts">
      {#each prompts as prompt (prompt)}<Button
          variant="outline"
          size="sm"
          disabled={inputDisabled}
          onclick={() => void choosePrompt(prompt)}>{prompt}</Button
        >{/each}
    </div>{/if}
</div>
