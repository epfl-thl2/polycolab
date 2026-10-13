<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { explain, projectContext } from '../svelte-lib/context';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  let {
    error,
    loading,
    onRetry,
    onComplete,
  }: { error: unknown; loading: boolean; onRetry: () => void; onComplete: () => void } = $props();
  const { history, auth } = projectContext();
  let username = $state('');
  let busy = $state(false);
  let saveError = $state('');
  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    saveError = '';
    try {
      await history.chooseUsername(username.trim().toLowerCase());
      onComplete();
    } catch (cause) {
      saveError =
        (cause as { status?: number }).status === 409
          ? 'That username is unavailable. Choose another.'
          : explain(cause);
    } finally {
      busy = false;
    }
  }
</script>

<main id="main" class="page narrow" tabindex="-1">
  {#if error}<DiscoveryState
      kind="error"
      title="Could not load your account"
      description={explain(error)}
      ><Button variant="outline" onclick={onRetry}>Retry</Button></DiscoveryState
    >
  {:else if loading}<LoadingState>Opening your account…</LoadingState>
  {:else}<h1>Choose your username</h1>
    <p>
      Your username appears on your public profile and research contributions. Choose it once to
      continue.
    </p>
    <form onsubmit={save}>
      <label for="public-username">Username</label>
      <Input
        id="public-username"
        bind:value={username}
        required
        minlength={3}
        maxlength={80}
        pattern={'[a-zA-Z0-9][a-zA-Z0-9_.\\-]{2,79}'}
        autocomplete="username"
        aria-describedby="username-hint"
      />
      <p id="username-hint">
        3–80 letters, numbers, dots, underscores or hyphens. Usernames use lowercase letters.
      </p>
      {#if saveError}<p role="alert">{saveError}</p>{/if}
      <Button type="submit" disabled={busy}>{busy ? 'Saving username…' : 'Continue'}</Button>
      <Button type="button" variant="ghost" onclick={() => void auth.signOut()}>Sign out</Button>
    </form>
  {/if}
</main>
