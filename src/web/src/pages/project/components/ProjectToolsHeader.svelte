<script lang="ts">
  import type { Component } from 'svelte';
  import type { IconProps } from '@lucide/svelte';
  import { PanelRightClose, X } from '@lucide/svelte';
  import { Button } from '../../../lib/components/ui/button';
  import * as Tooltip from '../../../lib/components/ui/tooltip';
  let {
    items,
    value,
    onselect,
    onclose,
    placement = 'desktop',
    detailsOnly = false,
    disabled = false,
  }: {
    items: ReadonlyArray<readonly [string, string, Component<IconProps>]>;
    value: string;
    onselect: (value: string) => void;
    onclose: () => void;
    placement?: 'desktop' | 'mobile';
    detailsOnly?: boolean;
    disabled?: boolean;
  } = $props();
  const closeLabel = $derived(
    placement === 'mobile' ? 'Close drawer' : detailsOnly ? 'Close details' : 'Collapse tools',
  );
</script>

<Tooltip.Provider delayDuration={250}>
  <header class="tools-header">
    {#if detailsOnly}<span class="details-heading">Details</span>{:else}<div
        class="tool-switcher"
        role="tablist"
        aria-label="Project tools"
      >
        {#each items as [id, label, Icon] (id)}
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  role="tab"
                  aria-label={label}
                  aria-selected={value === id}
                  {disabled}
                  onclick={() => onselect(id)}><Icon size={14} aria-hidden="true" /></button
                >
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content class="text-[11px] px-2 py-1">{label}</Tooltip.Content>
          </Tooltip.Root>
        {/each}
      </div>{/if}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <Button
            {...props}
            variant="ghost"
            size="icon-sm"
            aria-label={closeLabel}
            onclick={onclose}
            >{#if placement === 'desktop'}<PanelRightClose size={14} />{:else}<X
                size={14}
              />{/if}</Button
          >
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content class="text-[11px] px-2 py-1">
        {closeLabel}
      </Tooltip.Content>
    </Tooltip.Root>
  </header>
</Tooltip.Provider>

<style>
  .details-heading {
    font-size: 12px;
    font-weight: 600;
  }

  .tools-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--project-nav-height);
    box-sizing: border-box;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
    background: var(--background);
    flex-shrink: 0;
  }
  .tool-switcher {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tool-switcher button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border-radius: 4px;
    color: var(--muted-foreground);
  }
  .tool-switcher button[aria-selected='true'] {
    color: var(--sidebar-accent-foreground);
    background: var(--sidebar-accent);
  }
  .tool-switcher button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  .tools-header > :global(button) {
    width: 20px;
    height: 20px;
    min-height: 0;
    padding: 0;
  }
</style>
