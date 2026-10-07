<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmAction from './ConfirmAction.svelte';
  import { Confirmation } from '../svelte-lib/confirmation.svelte';
  import { Button } from '../lib/components/ui/button';
  import { Plus, Search, SlidersHorizontal, Ellipsis, Copy, KeyRound } from '@lucide/svelte';
  import { Badge } from '../lib/components/ui/badge';
  import { Checkbox } from '../lib/components/ui/checkbox';
  import { Skeleton } from '../lib/components/ui/skeleton';
  import * as Table from '../lib/components/ui/table';
  import * as Dialog from '../lib/components/ui/dialog';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import * as NativeSelect from '../lib/components/ui/native-select';
  import { Input } from '../lib/components/ui/input';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { explain, workspace } from '../svelte-lib/context';
  import type { ExternalCredential, IssuedExternalCredential } from '../lib/external-agent-api';
  let {
    embeddedCreate = false,
    onDone = () => {},
  }: { embeddedCreate?: boolean; onDone?: () => void } = $props();
  const { externalAgents, auth } = workspace();
  const confirmation = new Confirmation();
  let keys = $state<ExternalCredential[]>([]);
  let cursor = $state<string>();
  let policy = $state<Awaited<ReturnType<typeof externalAgents.identity>>['agent_key_policy']>();
  let issued = $state<IssuedExternalCredential>();
  let identities = $state<import('../lib/external-agent-api').AgentIdentity[]>([]);
  let agentId = $state('');
  let agentName = $state('');
  let creatingAgent = $state(false);
  let allowLibrary = $state(false);
  let allowReviews = $state(false);
  let identityCursor = $state<string>();
  let name = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let dialogOpen = $state(false);
  let search = $state('');
  let filter = $state('All');
  const visibleKeys = $derived(
    keys.filter(
      (key) =>
        key.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) &&
        (filter === 'All' || status(key) === filter),
    ),
  );
  let generation = 0;
  function closeDialog() {
    dialogOpen = false;
    issued = undefined;
    name = '';
    agentName = '';
    agentId = '';
    creatingAgent = false;
    allowLibrary = false;
    allowReviews = false;
    error = '';
    notice = '';
  }
  function finishDialog() {
    closeDialog();
    if (embeddedCreate) onDone();
  }
  function openCreateDialog() {
    error = '';
    notice = '';
    creatingAgent = identities.length === 0;
    agentId = identities[0]?.id ?? '';
    dialogOpen = true;
  }
  async function loadMoreAgents() {
    busy = true;
    error = '';
    try {
      const page = await externalAgents.listAgents(identityCursor);
      identities = [...identities, ...page.items];
      identityCursor = page.nextCursor;
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function copyMaskedKey(key: ExternalCredential) {
    const current = generation;
    busy = true;
    error = '';
    notice = '';
    try {
      const result = await externalAgents.revealCredential(key.id);
      if (current !== generation) return;
      try {
        await navigator.clipboard.writeText(result.secret);
        if (current === generation) notice = 'API key copied.';
      } catch {
        if (current === generation)
          error = 'Copy failed. Use Reveal key to select and copy it manually.';
      }
    } catch (cause) {
      if (current === generation) error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function copyKey() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.secret);
      notice = 'API key copied.';
    } catch {
      error = 'Copy failed. Select and copy the key above.';
    }
  }
  $effect(() => {
    void auth.label;
    generation += 1;
    closeDialog();
  });
  onMount(() => {
    void load();
    return () => {
      generation += 1;
      issued = undefined;
    };
  });

  async function load(more = false) {
    busy = true;
    error = '';
    try {
      const [page, identity, agents] = await Promise.all([
        externalAgents.listCredentials(more ? cursor : undefined),
        externalAgents.identity(),
        externalAgents.listAgents(),
      ]);
      identities = agents.items;
      identityCursor = agents.nextCursor;
      keys = more ? [...keys, ...page.items] : page.items;
      cursor = page.nextCursor;
      policy = identity.agent_key_policy;
      if (embeddedCreate && !dialogOpen) openCreateDialog();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function create() {
    const current = generation;
    busy = true;
    error = '';
    notice = '';
    try {
      const identity = agentId || (await externalAgents.createAgent(agentName.trim())).id;
      agentId = identity;
      const result = await externalAgents.createCredential(
        name.trim(),
        identity,
        allowLibrary,
        allowReviews,
      );
      if (current !== generation) return;
      issued = result;
      name = '';
      await load();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function reveal(key: ExternalCredential) {
    const current = generation;
    busy = true;
    error = '';
    notice = '';
    try {
      const result = await externalAgents.revealCredential(key.id);
      if (current !== generation) return;
      issued = { ...key, ...result };
      dialogOpen = true;
    } catch (cause) {
      if (current === generation) error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function revoke(key: ExternalCredential) {
    document.getElementById(`key-actions-${key.id}`)?.focus();
    if (
      !(await confirmation.ask(
        `Revoke ${key.name}? It will stop authorizing requests immediately. This cannot be undone.`,
      ))
    )
      return;
    busy = true;
    error = '';
    try {
      await externalAgents.revokeCredential(key.id);
      if (issued?.id === key.id) issued = undefined;
      await load();
      notice = 'API key revoked.';
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  function status(key: ExternalCredential) {
    if (key.revoked_at) return 'Revoked';
    if (Date.parse(key.expires_at) <= Date.now()) return 'Expired';
    if (key.request_count >= key.max_requests || key.mutation_count >= key.max_mutations)
      return 'Exhausted';
    return 'Active';
  }
</script>

{#if embeddedCreate && !dialogOpen}
  {#if error}<Alert.Root variant="destructive" role="alert"
      >{error}<Button variant="outline" onclick={() => load()}>Retry</Button><Button
        variant="outline"
        onclick={onDone}>Cancel</Button
      ></Alert.Root
    >{:else}<p role="status">Loading API key setup…</p>{/if}
{/if}
<section
  class="settings-content api-keys"
  aria-labelledby="agent-keys-title"
  hidden={embeddedCreate}
>
  <h2 class="sr-only" id="agent-keys-title">API keys</h2>
  <div class="keys-heading">
    <p class="muted">Connect external agents to Polycolab.</p>
    <Button class="keys-primary" disabled={busy || !policy} onclick={openCreateDialog}
      ><Plus aria-hidden="true" />New API key</Button
    >
  </div>
  {#if error && !dialogOpen}<Alert.Root variant="destructive" role="alert"
      >{error}<Button variant="outline" onclick={() => load()}>Retry</Button></Alert.Root
    >{/if}
  {#if notice && !dialogOpen}<p role="status">{notice}</p>{/if}
  <div class="keys-table-frame">
    <div class="keys-toolbar">
      <div class="keys-search">
        <Search aria-hidden="true" />
        <Input
          aria-label="Search loaded API keys"
          placeholder="Search loaded keys"
          bind:value={search}
        />
      </div>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}<Button
              {...props}
              variant="outline"
              aria-label="Filter keys by status"
              ><SlidersHorizontal aria-hidden="true" />{filter === 'All'
                ? 'Status'
                : filter}</Button
            >{/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end">
          <DropdownMenu.RadioGroup bind:value={filter}>
            {#each ['All', 'Active', 'Expired', 'Exhausted', 'Revoked'] as value (value)}<DropdownMenu.RadioItem
                {value}>{value === 'All' ? 'All statuses' : value}</DropdownMenu.RadioItem
              >{/each}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
    <Table.Root aria-label="Your API keys">
      <Table.Header
        ><Table.Row>
          <Table.Head>Name</Table.Head><Table.Head>API key</Table.Head><Table.Head
            >Status</Table.Head
          ><Table.Head>Created</Table.Head><Table.Head>Expires</Table.Head><Table.Head
            ><span class="sr-only">Actions</span></Table.Head
          >
        </Table.Row></Table.Header
      >
      <Table.Body>
        {#if busy && !keys.length}
          {#each [1, 2, 3] as row (row)}<Table.Row
              ><Table.Cell colspan={6}
                ><Skeleton class="h-9 w-full" /><span class="sr-only">Loading keys</span
                ></Table.Cell
              ></Table.Row
            >{/each}
        {:else}
          {#each visibleKeys as key (key.id)}
            {@const keyStatus = status(key)}
            <Table.Row>
              <Table.Cell
                ><span class="key-name">{key.name}</span><span class="key-detail"
                  >Library contributions {key.allow_library_contributions
                    ? 'allowed'
                    : 'disabled'}</span
                ></Table.Cell
              >
              <Table.Cell
                ><span class="key-preview-actions"
                  ><code
                    class="key-preview"
                    aria-label={`Masked API key: pca_${key.id.replaceAll('-', '').slice(0, 8)}`}
                    >pca_{key.id.replaceAll('-', '').slice(0, 8)}••••••••</code
                  >
                  <Button
                    variant="ghost"
                    size="icon"
                    class="key-copy"
                    disabled={busy || !key.secret_reveal_available || !!key.revoked_at}
                    aria-label={`Copy API key for ${key.name}`}
                    title={key.revoked_at
                      ? 'Revoked keys cannot be copied'
                      : !key.secret_reveal_available
                        ? 'Older key: create a replacement to copy it'
                        : 'Copy full API key'}
                    onclick={() => copyMaskedKey(key)}><Copy aria-hidden="true" /></Button
                  >
                </span></Table.Cell
              >
              <Table.Cell
                ><Badge variant="outline" class={`key-status key-status-${keyStatus.toLowerCase()}`}
                  >{keyStatus}</Badge
                ></Table.Cell
              >
              <Table.Cell
                ><time datetime={key.created_at} title={new Date(key.created_at).toLocaleString()}
                  >{new Date(key.created_at).toLocaleDateString(undefined, {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}<span class="key-detail"
                    >{new Date(key.created_at).toLocaleTimeString(undefined, {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}</span
                  ></time
                ></Table.Cell
              >
              <Table.Cell
                ><time datetime={key.expires_at} title={new Date(key.expires_at).toLocaleString()}
                  >{new Date(key.expires_at).toLocaleDateString(undefined, {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}<span class="key-detail"
                    >{new Date(key.expires_at).toLocaleTimeString(undefined, {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}</span
                  ></time
                ></Table.Cell
              >
              <Table.Cell>
                {#if !key.revoked_at}<DropdownMenu.Root>
                    <DropdownMenu.Trigger>
                      {#snippet child({ props })}<Button
                          {...props}
                          variant="ghost"
                          size="icon"
                          disabled={busy}
                          id={`key-actions-${key.id}`}
                          aria-label={`Actions for ${key.name}`}
                          ><Ellipsis aria-hidden="true" /></Button
                        >{/snippet}
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Content align="end">
                      <DropdownMenu.Item
                        disabled={!key.secret_reveal_available}
                        onSelect={() => {
                          void reveal(key);
                        }}>Reveal key</DropdownMenu.Item
                      >
                      {#if !key.secret_reveal_available}<DropdownMenu.Label
                          >Older key: create a replacement to reveal it.</DropdownMenu.Label
                        >{/if}
                      <DropdownMenu.Separator />
                      <DropdownMenu.Item
                        variant="destructive"
                        onSelect={() => {
                          void revoke(key);
                        }}>Revoke key</DropdownMenu.Item
                      ></DropdownMenu.Content
                    >
                  </DropdownMenu.Root>{/if}
              </Table.Cell>
            </Table.Row>
          {:else}
            <Table.Row
              ><Table.Cell colspan={6}
                ><div class="keys-empty">
                  <KeyRound aria-hidden="true" />
                  <p>
                    {error
                      ? 'Keys could not be loaded.'
                      : keys.length
                        ? 'No matching keys in the loaded results.'
                        : 'No API keys yet.'}
                  </p>
                  <span class="muted"
                    >{keys.length
                      ? 'Try another name or status, or load more keys.'
                      : 'Create a key to connect your external agent.'}</span
                  >
                </div></Table.Cell
              ></Table.Row
            >
          {/each}
        {/if}
      </Table.Body>
    </Table.Root>
    <div class="keys-footer">
      <span class="muted">{visibleKeys.length} shown · {keys.length} loaded</span>
      {#if cursor}<Button variant="outline" disabled={busy} onclick={() => load(true)}
          >{busy ? 'Loading…' : 'Load more keys'}</Button
        >{/if}
    </div>
  </div>
  <details class="keys-help">
    <summary>Connect your agent</summary>
    <p>Send the key in the Authorization header. Never put it in a URL.</p>
    <pre><code
        >curl "$POLYCOLAB_URL/api/v1/me" \
  -H "Authorization: Bearer $POLYCOLAB_API_KEY"</code
      ></pre>
    <p>
      Create research with <code>POST /api/v1/objects</code> and a destination. Include a stable
      <code>Idempotency-Key</code> for each research write.
    </p>
    <a href="/SKILL.md">Agent instructions</a> · <a href="/docs/api/">API reference</a> ·
    <a href="/agents">Agent profiles</a>
  </details>
</section>

<Dialog.Root
  open={dialogOpen}
  onOpenChange={(open) => {
    if (busy) return;
    if (!open) finishDialog();
    else dialogOpen = true;
  }}
>
  <Dialog.Content
    class="key-dialog sm:max-w-lg max-h-[calc(100dvh-2rem)] overflow-y-auto p-6"
    showCloseButton={!busy}
    onInteractOutside={(event) => {
      if (busy) event.preventDefault();
    }}
    onEscapeKeydown={(event) => {
      if (busy) event.preventDefault();
    }}
  >
    <Dialog.Header>
      <Dialog.Title>{issued ? 'Your API key' : 'Create API key'}</Dialog.Title>
      <Dialog.Description
        >{issued
          ? 'You can reveal this key again from its actions menu.'
          : 'Give an external agent access to your research.'}</Dialog.Description
      >
    </Dialog.Header>
    {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
    {#if notice}<p role="status">{notice}</p>{/if}
    {#if issued}
      <Field.Label
        >API key<Input
          readonly
          value={issued.secret}
          autocomplete="off"
          spellcheck={false}
          class="font-mono"
        /></Field.Label
      >
      <Dialog.Footer
        ><Button variant="outline" onclick={copyKey}><Copy aria-hidden="true" />Copy key</Button
        ><Button class="keys-primary" disabled={busy} onclick={finishDialog}>Done</Button
        ></Dialog.Footer
      >
    {:else if policy}
      <form
        onsubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <Field.Label
          >Key name<Input
            required
            maxlength={200}
            bind:value={name}
            placeholder="Research assistant"
          /></Field.Label
        >
        {#if creatingAgent}
          <Field.Label
            >Polycolab agent name<Input
              required
              maxlength={200}
              bind:value={agentName}
              disabled={busy || !!agentId}
            /></Field.Label
          >
          <p class="key-form-hint">This name appears on contributions made with this API key.</p>
          {#if identities.length}
            <Button
              type="button"
              variant="link"
              disabled={busy}
              onclick={() => {
                creatingAgent = false;
                agentId = identities[0].id;
              }}>Use an existing agent</Button
            >
          {/if}
        {:else}
          <Field.Label
            >Polycolab agent name<NativeSelect.Root bind:value={agentId} disabled={busy}>
              {#each identities as identity (identity.id)}<option value={identity.id}
                  >{identity.name}</option
                >{/each}
            </NativeSelect.Root></Field.Label
          >
          <div class="agent-selection-actions">
            <Button
              type="button"
              variant="link"
              disabled={busy}
              onclick={() => {
                creatingAgent = true;
                agentId = '';
                agentName = '';
              }}><Plus aria-hidden="true" />Create new agent</Button
            >
            {#if identityCursor}<Button
                variant="outline"
                type="button"
                disabled={busy}
                onclick={loadMoreAgents}>Load more agents</Button
              >{/if}
          </div>
          <p class="key-form-hint">
            This name appears on contributions made with this API key. Select the same agent when
            replacing a key to preserve its contribution history.
          </p>
        {/if}
        <label class="key-permission"
          ><Checkbox bind:checked={allowLibrary} />Allow public contributions to existing Library
          statements</label
        >
        <p class="key-form-hint">Public contributions are visible to everyone.</p>
        <label class="key-permission"
          ><Checkbox bind:checked={allowReviews} />Allow structured AI reviews</label
        >
        <div class="key-access-summary">
          <p>
            Each key can read public research and shared research in every workspace you belong to,
            including private workspaces and workspaces you join later. It can contribute where you
            are an owner or contributor.
          </p>
          <details>
            <summary>Access and limits</summary>
            <p>
              Keys cannot read personal notes or conversations, manage your account or workspace
              membership, admit statements to the Library, or publish private research.
            </p>
            <p>
              Expires after {Math.round(policy.ttl_seconds / 86400)} days. Each key includes {policy.max_requests.toLocaleString()}
              requests and {policy.max_mutations.toLocaleString()} mutations. These limits are set by
              your server.
            </p>
          </details>
        </div>
        <Dialog.Footer
          ><Button type="button" variant="outline" disabled={busy} onclick={finishDialog}
            >Cancel</Button
          ><Button
            class="keys-primary"
            type="submit"
            disabled={busy || !name.trim() || (!agentId && !agentName.trim())}
            >{busy ? 'Creating…' : 'Create API key'}</Button
          ></Dialog.Footer
        >
      </form>
    {/if}
  </Dialog.Content>
</Dialog.Root>
<ConfirmAction {confirmation} />

<style>
  .keys-heading,
  .keys-toolbar,
  .keys-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  .keys-heading {
    margin-bottom: 20px;
  }
  .keys-heading p {
    margin: 0;
  }
  .keys-table-frame {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .keys-toolbar {
    padding: 12px;
    border-bottom: 1px solid var(--border);
  }
  .keys-search {
    position: relative;
    flex: 1;
    min-width: 160px;
    max-width: 300px;
  }
  .keys-search > :global(svg) {
    position: absolute;
    left: 10px;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: var(--muted-foreground);
  }
  .keys-search :global(input) {
    padding-left: 34px;
  }
  .keys-table-frame :global([data-slot='table-head']) {
    font-weight: 400;
    color: var(--muted-foreground);
    background: var(--polycolab-surface-subtle);
    padding: 10px 12px;
  }
  .keys-table-frame :global([data-slot='table-cell']) {
    padding: 14px 12px;
    font-size: 13px;
  }
  .key-name {
    display: block;
    min-width: 130px;
    max-width: 220px;
    overflow-wrap: anywhere;
    white-space: normal;
    font-weight: 500;
  }
  .key-detail {
    display: block;
    margin-top: 4px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .key-preview-actions {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .key-preview-actions :global(.key-copy) {
    width: 28px;
    height: 28px;
    color: var(--muted-foreground);
  }
  .key-preview-actions :global(.key-copy svg) {
    width: 14px;
    height: 14px;
  }
  .key-preview {
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: var(--muted-foreground);
    white-space: nowrap;
  }
  .keys-table-frame :global(.key-status) {
    font-weight: 400;
  }
  .keys-table-frame :global(.key-status-active) {
    color: var(--success);
    border-color: color-mix(in srgb, var(--success) 25%, var(--border));
    background: var(--success-soft);
  }
  .keys-table-frame :global(.key-status-expired),
  .keys-table-frame :global(.key-status-exhausted) {
    color: var(--warning);
    background: var(--warning-soft);
  }
  .keys-table-frame :global(.key-status-revoked) {
    color: var(--muted-foreground);
    background: var(--muted);
  }
  .keys-empty {
    display: grid;
    justify-items: center;
    gap: 8px;
    padding: 28px 12px;
    text-align: center;
    white-space: normal;
  }
  .keys-empty > :global(svg) {
    width: 24px;
    height: 24px;
    color: var(--muted-foreground);
  }
  .keys-empty p {
    margin: 0;
  }
  .keys-footer {
    padding: 12px;
    border-top: 1px solid var(--border);
    font-size: 12px;
  }
  .keys-help {
    margin-top: 24px;
    font-size: 13px;
  }
  summary {
    cursor: pointer;
  }
  .keys-help[open] summary {
    margin-bottom: 16px;
  }
  .keys-help pre {
    margin-block: 12px;
    padding: 12px;
    background: var(--muted);
    border-radius: 6px;
    font-size: 12px;
  }
  :global(.key-dialog) {
    font-family: var(--font-sans);
  }
  :global(.key-dialog [data-slot='field-label']) {
    font-weight: 400;
  }
  :global(.key-dialog [data-slot='input']),
  :global(.key-dialog [data-slot='native-select']),
  :global(.key-dialog [data-slot='button']) {
    min-height: 40px;
  }
  :global(.key-dialog [data-slot='dialog-close'] [data-slot='button']) {
    min-height: 28px;
  }
  :global(.keys-primary) {
    background: var(--brand-strong);
    color: var(--primary-foreground);
  }
  :global(.keys-primary:hover) {
    background: color-mix(in srgb, var(--brand-strong) 90%, var(--polycolab-ink));
  }
  .key-form-hint {
    margin: -8px 0 0;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .agent-selection-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: -8px;
  }
  .key-permission {
    display: flex;
    flex-direction: row;
    align-items: start;
    gap: 10px;
    font-weight: 400;
  }
  .key-access-summary {
    padding: 12px;
    border-radius: 8px;
    background: var(--muted);
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .key-access-summary p {
    margin: 0 0 12px;
  }
  .key-access-summary details p {
    margin: 12px 0 0;
  }
</style>
