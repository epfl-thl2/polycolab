<script lang="ts">
  import { Tooltip as TooltipPrimitive } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

  let {
    children,
    class: className,
    sideOffset = 8,
    ...restProps
  }: WithoutChildrenOrChild<TooltipPrimitive.ContentProps> & { children: Snippet } = $props();
</script>

<TooltipPrimitive.Portal>
  <TooltipPrimitive.Content
    data-slot="tooltip-content"
    role="tooltip"
    {sideOffset}
    class={cn(
      'z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-tight text-background shadow-md',
      className,
    )}
    {...restProps}
  >
    {@render children()}
  </TooltipPrimitive.Content>
</TooltipPrimitive.Portal>
