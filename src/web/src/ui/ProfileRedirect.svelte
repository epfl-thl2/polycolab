<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from '../lib/components/ui/button';
  import { profileQuery, readProfile } from '../lib/ui-location';
  import { explain } from '../svelte-lib/context';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  let {
    search,
    hash,
    username,
    error,
    onRetry,
  }: { search: string; hash: string; username?: string; error: unknown; onRetry: () => void } =
    $props();
  $effect(() => {
    if (username) {
      const query = profileQuery(readProfile(search));
      void goto(`/profile/${username}${query ? `?${query}` : ''}${hash}`, {
        replaceState: true,
      });
    }
  });
</script>

<main id="main" class="page narrow" tabindex="-1">
  {#if error}<DiscoveryState
      kind="error"
      title="Could not open your profile"
      description={explain(error)}
      ><Button variant="outline" onclick={onRetry}>Retry</Button></DiscoveryState
    >{:else}<LoadingState>Opening your profile…</LoadingState>{/if}
</main>
