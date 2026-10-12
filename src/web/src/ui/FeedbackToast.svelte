<script lang="ts">
  import { CircleAlert, CircleCheck, X } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  let {
    message,
    variant = 'success',
    onDismiss,
  }: {
    message: string;
    variant?: 'success' | 'error';
    onDismiss: () => void;
  } = $props();
  let element: HTMLDivElement | undefined = $state();
  $effect(() => {
    // The top layer keeps notifications outside a modal's transform and scroll clipping.
    if (message && element) element.showPopover?.();
  });
</script>

{#if message}
  <div bind:this={element} popover="manual" class="feedback-toast" data-feedback-toast>
    {#if variant === 'error'}
      <CircleAlert aria-hidden="true" class="size-4 shrink-0 text-destructive" />
    {:else}
      <CircleCheck aria-hidden="true" class="size-4 shrink-0 text-green-600" />
    {/if}
    <p role={variant === 'error' ? 'alert' : 'status'} aria-atomic="true">{message}</p>
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Dismiss notification"
      onclick={onDismiss}
    >
      <X aria-hidden="true" />
    </Button>
  </div>
{/if}

<style>
  .feedback-toast {
    position: fixed;
    inset: auto 24px 24px auto;
    margin: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 12px;
    width: max-content;
    max-width: min(440px, calc(100vw - 32px));
    padding: 12px 12px 12px 16px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--popover);
    color: var(--popover-foreground);
    box-shadow: 0 4px 20px rgb(0 0 0 / 12%);
  }
  p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  @media (max-width: 640px) {
    .feedback-toast {
      right: 16px;
      bottom: 16px;
    }
  }
</style>
