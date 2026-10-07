<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import ConfirmAction from './ConfirmAction.svelte';
  import { Confirmation } from '../svelte-lib/confirmation.svelte';
  const confirmation = new Confirmation();
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { workspace, explain } from '../svelte-lib/context';
  const { api, query } = workspace();
  const profiles = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['profiles'],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listGatewayProfiles(pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  let draft = $state({ display_name: '', base_url: '', model_id: '', api_key: '' });
  let rotateId = $state('');
  let replacement = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  async function perform(task: () => Promise<unknown>, success: string) {
    busy = true;
    error = '';
    notice = '';
    try {
      await task();
      await query.invalidateQueries({ queryKey: ['profiles'] });
      notice = success;
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<section class="settings-content" aria-labelledby="gateway-profiles-title">
  <h2 class="sr-only" id="gateway-profiles-title">Builtin agents</h2>
  <p class="muted">Configure models used by the built-in agent. Stored keys are never returned.</p>
  {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}{#if notice}<p
      role="status"
      class="notice"
    >
      {notice}
    </p>{/if}
  <div class="split">
    <section class="card">
      <h2>Your profiles</h2>
      {#if $profiles.isPending}<LoadingState>Loading providers…</LoadingState
        >{:else if $profiles.isError}<Alert.Root variant="destructive" role="alert">
          {explain($profiles.error)}
        </Alert.Root>
        <Button type="submit" onclick={() => $profiles.refetch()}>Retry</Button
        >{:else if !$profiles.data?.pages[0].items.length}<p class="muted">
          Add a profile to send your first agent message.
        </p>{/if}
      <ul class="list">
        {#each $profiles.data?.pages.flatMap((p) => p.items) ?? [] as profile (profile.id)}<li>
            <h3>{profile.display_name}</h3>
            <p class="muted">{profile.model_id} · {profile.base_url}</p>
            <div class="row">
              <Button
                type="submit"
                variant="outline"
                class=""
                disabled={busy}
                onclick={() =>
                  perform(() => api.validateGatewayProfile(profile.id), 'Profile validated.')}
                >Validate</Button
              ><Button
                type="submit"
                variant="outline"
                class=""
                onclick={() => {
                  rotateId = profile.id;
                  replacement = '';
                }}>Rotate key</Button
              ><Button
                type="submit"
                variant="outline"
                class=""
                disabled={busy}
                onclick={async () => {
                  if (await confirmation.ask(`Delete ${profile.display_name}?`))
                    void perform(() => api.deleteGatewayProfile(profile.id), 'Profile deleted.');
                }}>Delete</Button
              >
            </div>
            {#if rotateId === profile.id}<form
                class="mt-4"
                onsubmit={(e) => {
                  e.preventDefault();
                  void perform(async () => {
                    await api.rotateGatewayProfile(profile.id, replacement);
                    replacement = '';
                    rotateId = '';
                  }, 'Key rotated.');
                }}
              >
                <Field.Label
                  >Replacement key<Input
                    type="password"
                    autocomplete="new-password"
                    required
                    bind:value={replacement}
                  /></Field.Label
                >
                <div class="row">
                  <Button type="submit" disabled={busy}>Save replacement</Button><Button
                    variant="outline"
                    class=""
                    type="button"
                    onclick={() => {
                      rotateId = '';
                      replacement = '';
                    }}>Cancel</Button
                  >
                </div>
              </form>{/if}
          </li>{/each}
      </ul>
      {#if $profiles.hasNextPage}<Button type="submit" onclick={() => $profiles.fetchNextPage()}
          >Load more profiles</Button
        >{/if}
    </section>
    <section class="card">
      <h2>Add a gateway</h2>
      <form
        onsubmit={(e) => {
          e.preventDefault();
          void perform(async () => {
            await api.createGatewayProfile({ ...draft });
            draft = { display_name: '', base_url: '', model_id: '', api_key: '' };
          }, 'Profile created.');
        }}
      >
        <Field.Label>Display name<Input required bind:value={draft.display_name} /></Field.Label
        ><Field.Label
          >Base URL<Input
            type="url"
            placeholder="https://api.example.com/v1"
            required
            bind:value={draft.base_url}
          /></Field.Label
        ><Field.Label>Model ID<Input required bind:value={draft.model_id} /></Field.Label
        ><Field.Label
          >API key<Input
            type="password"
            autocomplete="new-password"
            required
            bind:value={draft.api_key}
          /></Field.Label
        ><Button type="submit" disabled={busy}>{busy ? 'Working…' : 'Add profile'}</Button>
      </form>
    </section>
  </div>
</section>

<ConfirmAction {confirmation} />
