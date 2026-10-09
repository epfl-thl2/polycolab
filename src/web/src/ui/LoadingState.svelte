<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Skeleton } from '../lib/components/ui/skeleton';
  let { children }: { children: Snippet } = $props();
</script>

<div role="status" class="my-4 grid gap-3 text-sm text-muted-foreground">
  <span>{@render children()}</span>
  <div aria-hidden="true" class="grid max-w-sm gap-2">
    <Skeleton class="h-3 w-full" />
    <Skeleton class="h-3 w-2/3" />
  </div>
</div>
