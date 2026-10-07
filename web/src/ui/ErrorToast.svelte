<script lang="ts">
  import { CircleAlert, X } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  let { message, placement = 'bottom' }: { message: string; placement?: 'top' | 'bottom' } =
    $props();
  let visible = $derived(Boolean(message));
</script>

{#if visible}
  <div class="error-toast" class:error-toast-top={placement === 'top'}>
    <CircleAlert aria-hidden="true" class="size-4 shrink-0 text-destructive" />
    <p role="alert">{message}</p>
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label="Dismiss error"
      onclick={() => (visible = false)}
    >
      <X aria-hidden="true" />
    </Button>
  </div>
{/if}

<style>
  .error-toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
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
  .error-toast-top {
    top: 60px;
    bottom: auto;
  }
  p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
</style>
