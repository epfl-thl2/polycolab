<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { Dialog } from 'bits-ui';
  import { CircleAlert, CircleCheck, Info, X } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import { explain } from '../svelte-lib/context';
  import type { Notification, Notifications } from '../svelte-lib/notifications.svelte';
  let { notifications }: { notifications: Notifications } = $props();
  let expanded = $state(false);
  let target = $state.raw<HTMLElement>();
  let element = $state<HTMLDivElement>();
  let busy = $state<string[]>([]);
  const visible = $derived(expanded ? notifications.items : notifications.items.slice(0, 3));
  const popoverSupported =
    typeof HTMLElement !== 'undefined' && typeof HTMLElement.prototype.showPopover === 'function';
  $effect(() => {
    if (element && visible.length) element.showPopover?.();
  });
  onMount(() => {
    const syncTarget = () => {
      const dialogs = document.querySelectorAll<HTMLElement>(
        '[data-slot="dialog-content"][data-state="open"], [data-slot="alert-dialog-content"][data-state="open"], [data-slot="sheet-content"][data-state="open"]',
      );
      const next = dialogs.item(dialogs.length - 1) || document.body;
      if (untrack(() => target) !== next) target = next;
    };
    syncTarget();
    const observer = new MutationObserver(syncTarget);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-state'],
    });
    let last = performance.now();
    const visibilityChanged = () => {
      last = performance.now();
    };
    document.addEventListener('visibilitychange', visibilityChanged);
    const timer = setInterval(() => {
      const now = performance.now();
      if (!document.hidden)
        notifications.advance(
          now - last,
          visible.map((item) => item.key),
        );
      last = now;
    }, 250);
    return () => {
      observer.disconnect();
      clearInterval(timer);
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  });
  async function act(item: Notification) {
    if (!item.action || !('run' in item.action) || busy.includes(item.key)) return;
    busy = [...busy, item.key];
    try {
      await item.action.run();
    } catch (error) {
      notifications.publish({ ...item, kind: 'error', message: explain(error) });
    } finally {
      busy = busy.filter((key) => key !== item.key);
    }
  }
  function pause(event: Event, key: string) {
    const node = event.currentTarget as HTMLElement;
    const focus =
      event.type === 'focusout' ? (event as FocusEvent).relatedTarget : document.activeElement;
    notifications.pause(
      key,
      node.matches(':hover') || node.contains(focus instanceof Node ? focus : null),
    );
  }
</script>

{#if visible.length}
  <Dialog.Portal to={target ?? 'body'}>
    <div
      bind:this={element}
      popover={popoverSupported ? 'manual' : undefined}
      class="toast-stack"
      data-toast-stack
      role="region"
      aria-label="Notifications"
    >
      {#each visible as item (item.key)}
        <div
          role="group"
          aria-label={`${item.kind} notification`}
          class="feedback-toast"
          data-feedback-toast
          onmouseenter={(event) => pause(event, item.key)}
          onmouseleave={(event) => pause(event, item.key)}
          onfocusin={(event) => pause(event, item.key)}
          onfocusout={(event) => pause(event, item.key)}
        >
          {#if item.kind === 'error' || item.kind === 'warning'}
            <CircleAlert aria-hidden="true" class="size-4 shrink-0 text-destructive" />
          {:else if item.kind === 'info'}
            <Info aria-hidden="true" class="size-4 shrink-0" />
          {:else}
            <CircleCheck aria-hidden="true" class="size-4 shrink-0 text-green-600" />
          {/if}
          <div class="toast-content">
            <p
              role={item.kind === 'error' || item.kind === 'warning' ? 'alert' : 'status'}
              aria-atomic="true"
            >
              {item.message}
            </p>
            {#if item.action}
              {#if 'href' in item.action}<a href={item.action.href}>{item.action.label}</a>
              {:else}<Button
                  variant="link"
                  size="sm"
                  disabled={busy.includes(item.key)}
                  onclick={() => act(item)}>{item.action.label}</Button
                >{/if}
            {/if}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss notification"
            onclick={() => notifications.dismiss(item.key)}><X aria-hidden="true" /></Button
          >
        </div>
      {/each}
      {#if notifications.items.length > 3}<Button
          variant="outline"
          size="sm"
          onclick={() => (expanded = !expanded)}
          >{expanded
            ? 'Show fewer notifications'
            : `More notifications (${notifications.items.length - 3})`}</Button
        >{/if}
    </div>
  </Dialog.Portal>
{/if}

<style>
  .toast-stack {
    position: fixed;
    inset: auto 24px 24px auto;
    margin: 0;
    z-index: 100;
    display: grid;
    gap: 8px;
    width: min(440px, calc(100vw - 32px));
    max-height: calc(100dvh - 48px);
    overflow: auto;
    border: 0;
    padding: 0;
    background: transparent;
    color: var(--popover-foreground);
  }
  .toast-stack[popover]:not(:popover-open) {
    display: none;
  }
  .feedback-toast {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 12px 12px 16px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--popover);
    box-shadow: 0 4px 20px rgb(0 0 0 / 12%);
  }
  .toast-content {
    min-width: 0;
    flex: 1;
  }
  p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  a {
    font-size: 13px;
    color: var(--primary);
    text-underline-offset: 3px;
  }
  .toast-content :global(button) {
    padding-left: 0;
  }
  @media (max-width: 640px) {
    .toast-stack {
      right: max(16px, env(safe-area-inset-right));
      bottom: max(16px, env(safe-area-inset-bottom));
    }
    .feedback-toast :global(button) {
      min-height: 44px;
    }
  }
</style>
