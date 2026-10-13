<script lang="ts">
  import FeedbackToast from './FeedbackToast.svelte';
  import LoadingState from './LoadingState.svelte';
  import ConfirmAction from './ConfirmAction.svelte';
  import { Confirmation } from '../svelte-lib/confirmation.svelte';
  import { Ellipsis, Bot, Search } from '@lucide/svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import * as Table from '../lib/components/ui/table';
  import * as Dialog from '../lib/components/ui/dialog';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import { Badge } from '../lib/components/ui/badge';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { GatewayProfile } from '../lib/research-api';
  const confirmation = new Confirmation();
  const { api, query } = projectContext();
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
  let editing = $state<GatewayProfile>();
  let replacement = $state('');
  let dialogOpen = $state(false);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let checks = $state<Record<string, string>>({});
  let search = $state('');
  const loadedProfiles = $derived($profiles.data?.pages.flatMap((page) => page.items) ?? []);
  const visibleProfiles = $derived(
    loadedProfiles.filter((profile) =>
      [profile.display_name, profile.model_id, profile.base_url].some((value) =>
        value.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
      ),
    ),
  );
  function closeDialog() {
    dialogOpen = false;
    draft = { display_name: '', base_url: '', model_id: '', api_key: '' };
    replacement = '';
    editing = undefined;
    error = '';
  }
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
  async function testConnection(profile: GatewayProfile) {
    checks[profile.id] = 'Testing…';
    await perform(async () => {
      try {
        await api.validateGatewayProfile(profile.id);
        checks[profile.id] = 'Connection verified';
      } catch (reason) {
        checks[profile.id] = 'Test failed';
        throw reason;
      }
    }, `Connection to ${profile.display_name} verified.`);
  }
</script>

<section class="settings-content" aria-labelledby="ai-providers-title">
  <div class="providers-heading settings-section-heading">
    <div>
      <h2 id="ai-providers-title">Model providers</h2>
    </div>
    <Button
      disabled={busy}
      onclick={() => {
        closeDialog();
        notice = '';
        dialogOpen = true;
      }}
    >
      Add model provider
    </Button>
  </div>
  {#if !dialogOpen}<FeedbackToast
      message={error || notice}
      variant={error ? 'error' : 'success'}
      onDismiss={() => {
        error = '';
        notice = '';
      }}
    />{/if}
  {#if $profiles.isPending}
    <LoadingState>Loading providers…</LoadingState>
  {:else if $profiles.isError}
    <Alert.Root variant="destructive" role="alert">{explain($profiles.error)}</Alert.Root>
    <Button variant="outline" onclick={() => $profiles.refetch()}>Retry</Button>
  {:else}
    <div class="providers-table-frame">
      <div class="providers-toolbar">
        <div class="providers-search">
          <Search aria-hidden="true" />
          <Input
            aria-label="Search loaded model providers"
            placeholder="Search loaded providers"
            bind:value={search}
          />
        </div>
      </div>
      <Table.Root aria-label="Your model providers">
        <Table.Header
          ><Table.Row>
            <Table.Head>Name</Table.Head><Table.Head>Model</Table.Head><Table.Head
              >API key</Table.Head
            ><Table.Head>Connection</Table.Head><Table.Head
              ><span class="sr-only">Actions</span></Table.Head
            >
          </Table.Row></Table.Header
        >
        <Table.Body>
          {#each visibleProfiles as profile (profile.id)}
            <Table.Row>
              <Table.Cell
                ><span class="provider-name">{profile.display_name}</span><span
                  class="provider-endpoint">{profile.base_url}</span
                ></Table.Cell
              >
              <Table.Cell><span class="provider-model">{profile.model_id}</span></Table.Cell>
              <Table.Cell
                >{#if profile.api_key_preview}<code class="provider-preview"
                    >{profile.api_key_preview}</code
                  >{:else}<span class="muted">Preview unavailable</span>{/if}</Table.Cell
              >
              <Table.Cell
                ><Badge variant="outline" title="Connection test result from this page visit"
                  >{checks[profile.id] ?? 'Not tested'}</Badge
                ></Table.Cell
              >
              <Table.Cell>
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger>
                    {#snippet child({ props })}
                      <Button
                        {...props}
                        variant="ghost"
                        size="icon"
                        disabled={busy}
                        aria-label={`Actions for ${profile.display_name}`}
                        ><Ellipsis aria-hidden="true" /></Button
                      >
                    {/snippet}
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Content align="end">
                    <DropdownMenu.Item
                      onSelect={() => {
                        void testConnection(profile);
                      }}>Test connection</DropdownMenu.Item
                    >
                    <DropdownMenu.Item
                      onSelect={() => {
                        closeDialog();
                        notice = '';
                        editing = profile;
                        dialogOpen = true;
                      }}>Replace API key</DropdownMenu.Item
                    >
                    <DropdownMenu.Separator />
                    <DropdownMenu.Item
                      variant="destructive"
                      onSelect={async () => {
                        if (await confirmation.ask(`Delete ${profile.display_name}?`))
                          void perform(
                            () => api.deleteGatewayProfile(profile.id),
                            'AI provider deleted.',
                          );
                      }}>Delete provider</DropdownMenu.Item
                    >
                  </DropdownMenu.Content>
                </DropdownMenu.Root>
              </Table.Cell>
            </Table.Row>
          {:else}
            <Table.Row
              ><Table.Cell colspan={5}>
                <div class="providers-empty">
                  <Bot aria-hidden="true" />
                  <p>
                    {loadedProfiles.length
                      ? 'No matching providers in the loaded results.'
                      : 'No model providers yet.'}
                  </p>
                  <span class="muted"
                    >{loadedProfiles.length
                      ? 'Try another name, model, or endpoint, or load more providers.'
                      : 'Add a model provider to send your first agent message.'}</span
                  >
                </div>
              </Table.Cell></Table.Row
            >
          {/each}
        </Table.Body>
      </Table.Root>
      <div class="providers-footer">
        <span class="muted">Showing {visibleProfiles.length} out of {loadedProfiles.length}</span>
        {#if $profiles.hasNextPage}<Button
            variant="outline"
            disabled={$profiles.isFetchingNextPage}
            onclick={() => $profiles.fetchNextPage()}>Load more providers</Button
          >{/if}
      </div>
    </div>
    <p class="providers-help muted">
      Full API keys are never shown again. Masked previews help you recognize saved keys. Keys saved
      before previews were available show a preview after replacement. Connection results apply to
      this page visit.
    </p>
  {/if}
</section>

<Dialog.Root
  open={dialogOpen}
  onOpenChange={(open) => {
    if (!busy && !open) closeDialog();
  }}
>
  <Dialog.Content
    class="sm:max-w-lg max-h-[calc(100dvh-2rem)] overflow-y-auto p-6"
    showCloseButton={!busy}
    onInteractOutside={(event) => {
      if (busy) event.preventDefault();
    }}
    onEscapeKeydown={(event) => {
      if (busy) event.preventDefault();
    }}
  >
    <Dialog.Header>
      <Dialog.Title>{editing ? 'Replace API key' : 'Add model provider'}</Dialog.Title>
      <Dialog.Description
        >{editing
          ? `Update the key for ${editing.display_name}.`
          : 'Enter your provider’s endpoint, model, and API key. You can test the connection after saving.'}</Dialog.Description
      >
    </Dialog.Header>
    {#if dialogOpen}
      <FeedbackToast
        message={error || notice}
        variant={error ? 'error' : 'success'}
        onDismiss={() => {
          error = '';
          notice = '';
        }}
      />
    {/if}
    <form
      onsubmit={(event) => {
        event.preventDefault();
        const profile = editing;
        void perform(
          async () => {
            if (profile) {
              await api.rotateGatewayProfile(profile.id, replacement);
              delete checks[profile.id];
            } else await api.createGatewayProfile({ ...draft });
            closeDialog();
          },
          profile ? 'API key replaced.' : 'AI provider added.',
        );
      }}
    >
      {#if editing}
        <Field.Label
          >Replacement key<Input
            type="password"
            autocomplete="new-password"
            required
            disabled={busy}
            bind:value={replacement}
          /></Field.Label
        >
      {:else}
        <Field.Label
          >Display name<Input
            required
            disabled={busy}
            bind:value={draft.display_name}
            placeholder="Research assistant"
          /></Field.Label
        >
        <Field.Label
          >API endpoint<Input
            type="url"
            placeholder="https://api.example.com/v1"
            required
            disabled={busy}
            bind:value={draft.base_url}
          /></Field.Label
        >
        <Field.Label
          >Model ID<Input required disabled={busy} bind:value={draft.model_id} /></Field.Label
        >
        <Field.Label
          >API key<Input
            type="password"
            autocomplete="new-password"
            required
            disabled={busy}
            bind:value={draft.api_key}
          /></Field.Label
        >
      {/if}
      <Dialog.Footer>
        <Button type="button" variant="outline" disabled={busy} onclick={closeDialog}>Cancel</Button
        >
        <Button type="submit" disabled={busy}
          >{busy ? 'Saving…' : editing ? 'Save replacement' : 'Save provider'}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
<ConfirmAction {confirmation} />

<style>
  .providers-heading,
  .providers-toolbar,
  .providers-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .providers-heading h2 {
    margin: 0;
  }
  .providers-table-frame {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .providers-toolbar {
    padding: 12px;
    border-bottom: 1px solid var(--border);
  }
  .providers-search {
    position: relative;
    flex: 1;
    min-width: 160px;
    max-width: 300px;
  }
  .providers-search > :global(svg) {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: var(--muted-foreground);
  }
  .providers-search :global(input) {
    padding-left: 34px;
  }
  .providers-table-frame :global([data-slot='table-head']) {
    font-weight: 400;
    color: var(--muted-foreground);
    background: var(--polycolab-surface-subtle);
    padding: 10px 12px;
  }
  .providers-table-frame :global([data-slot='table-cell']) {
    padding: 10px 12px;
    font-size: 13px;
  }
  .provider-name,
  .provider-model {
    display: block;
    min-width: 100px;
    max-width: 220px;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .provider-name {
    font-weight: 500;
  }
  .provider-endpoint {
    display: block;
    max-width: 220px;
    margin-top: 4px;
    font-size: 12px;
    color: var(--muted-foreground);
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .provider-preview {
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .providers-table-frame :global([data-slot='badge']) {
    font-weight: 400;
  }
  .providers-footer {
    padding: 12px;
    border-top: 1px solid var(--border);
    font-size: 12px;
  }
  .providers-empty {
    display: grid;
    justify-items: center;
    gap: 8px;
    padding: 28px 12px;
    text-align: center;
    white-space: normal;
  }
  .providers-empty > :global(svg) {
    width: 24px;
    height: 24px;
    color: var(--muted-foreground);
  }
  .providers-empty p {
    margin: 0;
  }
  .providers-help {
    margin-top: 16px;
    font-size: 12px;
  }
</style>
