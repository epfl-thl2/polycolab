<script lang="ts">
  import LoadingState from '../../../ui/LoadingState.svelte';
  import FeedbackToast from '../../../ui/FeedbackToast.svelte';
  import * as Field from '../../../lib/components/ui/field';
  import * as DropdownMenu from '../../../lib/components/ui/dropdown-menu';
  import { NativeSelect } from '../../../lib/components/ui/native-select';
  import { Button } from '../../../lib/components/ui/button';
  import { Input } from '../../../lib/components/ui/input';
  import { Textarea } from '../../../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { projectContext, explain } from '../../../svelte-lib/context';
  import { advancesCursor, statusFromEvent } from '../../../svelte-lib/conversation-events';
  import type { AgentRun, ConversationSharing } from '../../../lib/conversations-api';
  import ConversationTranscriptItem from '../components/ConversationTranscriptItem.svelte';
  import ConversationTranscript from '../components/ConversationTranscript.svelte';
  import Markdown from '../../../ui/Markdown.svelte';
  import ChatComposer from '../../../ui/ChatComposer.svelte';
  import { ChevronDown, LoaderCircle, Sparkles } from '@lucide/svelte';
  import { Popover } from 'bits-ui';
  import { chatPanelPortal } from '../../../lib/chat-panel-portal';
  import { chatDrafts, ChatDrafts, chatDraftKey } from '../../../lib/chat-drafts.svelte';
  import {
    createProjectConversations,
    conversationOptions,
    conversationKeys,
    invalidateConversation,
  } from '../../../lib/conversation-queries';
  import { tick, untrack } from 'svelte';
  let {
    projectId,
    conversationId,
    worktreeId,
    view,
    isVisible = true,
    draftKey,
    onCreated,
  }: {
    projectId: string;
    conversationId?: string;
    worktreeId?: string;
    view?: 'chat' | 'list';
    isVisible?: boolean;
    draftKey?: string;
    onCreated?: (id: string) => void;
  } = $props();
  const allConversations = $derived(
    view ? view === 'list' : page.url.pathname.endsWith('/conversations'),
  );
  const { api, agents, query, capabilities: applicationCapabilities } = projectContext();
  const viewer = createQuery(
    toStore(() => ({ queryKey: ['chat-viewer'], queryFn: () => api.currentUser() })),
  );
  const executionEnabled = $derived(applicationCapabilities?.enabled('agent_execution') ?? false);
  const repository = projectContext().repository;
  const collaborative = projectContext().collaborative;
  const basicFiles = projectContext().basicFiles;
  let useProjectFiles = $state(false);
  const repositoryState = createQuery(
    toStore(() => ({
      queryKey: ['project-repository-availability', projectId],
      enabled: Boolean(repository),
      queryFn: () => repository!.state(projectId),
    })),
  );
  const conversationRepository = createQuery(
    toStore(() => ({
      queryKey: ['conversation-repository', projectId, conversationId],
      enabled: Boolean(repository && conversationId && $repositoryState.data?.enabled),
      queryFn: () => repository!.conversation(projectId, conversationId!),
    })),
  );
  let agentId = $state('');
  let providerConnectionId = $state('');
  let harness = $state<'platform' | 'codex'>('platform');
  let sharing = $state(false);
  let sharingMode = $state<ConversationSharing>('members_can_view');
  let titleDraft = $state('');
  let editingTitle = $state(false);
  const draftStore = chatDrafts() ?? new ChatDrafts();
  const entryKey = untrack(
    () =>
      draftKey ??
      chatDraftKey(
        projectId,
        conversationId
          ? `/projects/${projectId}/conversations/${conversationId}`
          : page.url.pathname + page.url.search,
      ),
  );
  const chatDraft = untrack(() => draftStore.get(entryKey));
  let reconciliationLoaded = false;
  $effect(() => {
    if (!collaborative || reconciliationLoaded || typeof location === 'undefined') return;
    const id = new URL(location.href).searchParams.get('reconcile');
    if (!id) return;
    reconciliationLoaded = true;
    void collaborative.api.changeSets(projectId).then((changeSets) => {
      const changeSet = changeSets.find((value) => value.id === id && value.status === 'pending');
      if (changeSet)
        chatDraft.message =
          'Please reconcile this pending file result with the current shared workspace. Preserve newer human changes, review the original and proposed contents below, and validate the combined result.\n\n' +
          JSON.stringify(changeSet.changes);
    });
  });
  const promptStarters = [
    'Summarize this project',
    'Explore the project files',
    'Help me test a change',
    'Review my work',
    'Suggest next steps',
  ];
  let artifactIds = $state('');
  const ids = (text: string) => [...new Set(text.split(/[\s,]+/).filter(Boolean))];
  let busy = $state(false);
  let error = $state('');
  let connection = $state('Connecting…');
  let run = $state<
    Pick<AgentRun, 'id' | 'status' | 'can_interrupt'> & { failure_code?: string | null }
  >();
  let exportRunId = $state('');
  const runRepository = createQuery(
    toStore(() => ({
      queryKey: ['run-repository', projectId, exportRunId || run?.id, run?.status],
      enabled: Boolean(
        repository && $conversationRepository.data?.enabled && (exportRunId || run?.id),
      ),
      queryFn: () => repository!.run(projectId, exportRunId || run!.id),
    })),
  );
  let accessDeniedId = $state<string>();
  const canReadConversation = $derived(
    Boolean(conversationId && accessDeniedId !== conversationId),
  );
  let streaming = $state('');
  let streamConversationId: string | undefined;
  let streamCursor: string | undefined;
  const conversations = createProjectConversations(
    agents,
    () => projectId,
    () => allConversations,
  );
  const conversation = createQuery(
    toStore(() => ({
      ...conversationOptions(agents, conversationId, isVisible),
      enabled: canReadConversation,
    })),
  );
  const worktrees = projectContext().worktrees;
  const currentWorktreeId = $derived(
    conversationId ? $conversation.data?.working_context.worktree_id : worktreeId,
  );
  const worktree = createQuery(
    toStore(() => ({
      queryKey: ['project-worktree', projectId, currentWorktreeId],
      enabled: Boolean(worktrees && currentWorktreeId),
      queryFn: () => worktrees!.get(projectId, currentWorktreeId!),
      refetchInterval: isVisible && currentWorktreeId ? 5000 : false,
    })),
  );
  const runs = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['conversation-runs', conversationId],
      enabled: canReadConversation,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listRuns(conversationId!, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
      refetchInterval: isVisible ? 5000 : false,
    })),
  );
  $effect(() => {
    const pages = $runs.data?.pages;
    if ($runs.hasNextPage) {
      void $runs.fetchNextPage();
      return;
    }
    const latest = pages?.flatMap((p) => p.items).at(-1);
    if (latest) run = latest;
  });
  const capabilities = createQuery(
    toStore(() => ({
      queryKey: ['agent-capabilities'],
      queryFn: () => agents.capabilities(),
      refetchInterval: 10000,
    })),
  );
  const hostedAvailable = $derived($capabilities.data?.hosted_agents ?? false);
  const selectedExportRunId = $derived(
    exportRunId ||
      $runs.data?.pages
        .flatMap((p) => p.items)
        .filter((item) => item.status === 'COMPLETED' && item.can_read_private_context)
        .at(-1)?.id ||
      '',
  );
  const exports = createQuery(
    toStore(() => ({
      queryKey: ['run-artifacts', selectedExportRunId],
      enabled: Boolean(selectedExportRunId),
      queryFn: () => agents.listArtifacts(selectedExportRunId),
    })),
  );
  async function downloadExport(id: string, name: string) {
    try {
      const blob = await agents.downloadArtifact(selectedExportRunId, id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      error = explain(reason);
    }
  }
  const platformModels = createQuery(
    toStore(() => ({ queryKey: ['platform-models'], queryFn: () => api.listPlatformModels() })),
  );
  const selectedHarness = $derived(
    !conversationId ? harness : ($conversation.data?.configuration?.harness ?? 'platform'),
  );
  const sharedModels = $derived(
    ($platformModels.data ?? []).filter(
      (model) => model.uses.includes('project_chat') && model.harnesses.includes(selectedHarness),
    ),
  );
  const connections = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['connections'],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listProviderConnections(pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const messages = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['conversation-items', conversationId],
      enabled: canReadConversation,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listItems(conversationId!, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const available = createQuery(
    toStore(() => ({ queryKey: ['agents'], queryFn: () => agents.listAgents() })),
  );
  const availableAgents = $derived($available.data?.items ?? []);
  const personalConnections = $derived(
    $connections.data?.pages.flatMap((connectionPage) => connectionPage.items) ?? [],
  );
  const availableConnections = $derived([...sharedModels, ...personalConnections]);
  $effect(() => {
    // Existing API versions still require a preset identity; it is not a composer choice.
    const defaultAgent = availableAgents
      .filter((agent) => agent.agent_kind === 'RESEARCHER')
      .sort((a, b) => b.version - a.version)[0];
    if (!agentId && defaultAgent) agentId = defaultAgent.id;
  });
  $effect(() => {
    if ($platformModels.isPending) return;
    const selectedShared = ($platformModels.data ?? []).find(
      (model) => model.id === providerConnectionId,
    );
    if (
      !providerConnectionId ||
      (selectedShared && !sharedModels.some((model) => model.id === providerConnectionId))
    )
      providerConnectionId =
        sharedModels.find((model) => model.default_for.includes('project_chat'))?.id ??
        availableConnections[0]?.id ??
        '';
  });
  const active = $derived(
    run && ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(run.status),
  );
  const newChatSendReason = $derived.by(() => {
    if (busy) return 'Sending…';
    if (worktreeId && $worktree.isPending) return 'Opening worktree…';
    if (worktreeId && $worktree.isError) return 'This worktree is unavailable.';
    if ($worktree.data?.removed_at) return 'This worktree is removed.';
    if (!executionEnabled) return 'Hosted execution is disabled.';
    if (harness === 'codex' && !hostedAvailable) return 'Codex is unavailable.';
    if (!agentId) return 'Loading agent configuration…';
    if (!providerConnectionId) return 'Choose an AI provider.';
    if (!chatDraft.message.trim()) return 'Write a message to send.';
    return '';
  });
  const conversationSendReason = $derived.by(() => {
    if ($conversation.data?.origin === 'legacy_direct')
      return 'Retired direct-chat history is read-only.';
    if (!$conversation.data?.capabilities.can_send)
      return 'You can read this conversation but cannot send messages.';
    if (busy) return 'Working…';
    if ($worktree.data?.removed_at) return 'This worktree is removed.';
    if ($conversation.data?.status === 'archived') return 'This conversation is archived.';
    if (!executionEnabled) return 'Hosted execution is disabled.';
    if (!$capabilities.data?.execution_available) return 'Agent execution is unavailable.';
    if (active) return 'Wait for the current run to finish.';
    if (!providerConnectionId) return 'Choose a model connection.';
    if (!chatDraft.message.trim()) return 'Write a message to send.';
    return '';
  });
  async function create(event: SubmitEvent) {
    event.preventDefault();
    if (
      busy ||
      (worktreeId && ($worktree.isPending || $worktree.isError || $worktree.data?.removed_at)) ||
      !executionEnabled ||
      !chatDraft.message.trim() ||
      !providerConnectionId ||
      (harness === 'codex' && !hostedAvailable)
    )
      return;
    busy = true;
    error = '';
    const submittedMessage = chatDraft.message;
    try {
      const choice = $available.data?.items.find((agent) => agent.id === agentId);
      if (!choice || (choice.version !== 1 && choice.version !== 2 && choice.version !== 3))
        throw new Error('Choose an available agent version.');
      if (!chatDraft.startingConversationId) {
        const created = await agents.createConversation({
          project_id: projectId,
          ...(worktreeId ? { worktree_id: worktreeId } : {}),
          agent_kind: choice.agent_kind,
          agent_version: choice.version,
          ...(harness === 'codex' ? { harness: 'codex' as const } : {}),
        });
        query.setQueryData(conversationKeys.detail(created.id), created);
        chatDraft.startingConversationId = created.id;
        await invalidateConversation(query, projectId);
      }
      if (!worktreeId && useProjectFiles && repository)
        await repository.enableConversation(projectId, chatDraft.startingConversationId);
      const body = {
        content_md: submittedMessage.trim(),
        provider_connection_id: providerConnectionId,
      };
      const serialized = JSON.stringify(body);
      if (chatDraft.startRequest?.body !== serialized)
        chatDraft.startRequest = { key: crypto.randomUUID(), body: serialized };
      await collaborative?.flush();
      await agents.queueTurn(chatDraft.startingConversationId, {
        ...body,
        client_request_id: chatDraft.startRequest.key,
      });
      if (chatDraft.message === submittedMessage) chatDraft.message = '';
      if (chatDraft.message) {
        const savedKey = chatDraftKey(
          projectId,
          `/projects/${projectId}/conversations/${chatDraft.startingConversationId}`,
        );
        draftStore.get(savedKey).message = chatDraft.message;
      }
      draftStore.delete(entryKey);
      void invalidateConversation(query, projectId, chatDraft.startingConversationId);
      if (onCreated) onCreated(chatDraft.startingConversationId);
      else await goto(`/projects/${projectId}/conversations/${chatDraft.startingConversationId}`);
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  $effect(() => {
    const id = conversationId;
    if (
      !isVisible ||
      !canReadConversation ||
      !id ||
      !$conversation.data?.capabilities.can_stream ||
      $conversation.data.project_id !== projectId
    )
      return;
    if (streamConversationId !== id) {
      streamConversationId = id;
      streamCursor = undefined;
      streaming = '';
    }
    const controller = new AbortController();
    let delay: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    async function consume() {
      try {
        connection = 'Connected';
        for await (const event of agents.stream(id!, streamCursor, controller.signal)) {
          if (controller.signal.aborted) return;
          if (!advancesCursor(streamCursor, event.id)) continue;
          streamCursor = event.id;
          attempt = 0;
          const kind = event.data.kind;
          if (kind === 'ASSISTANT_DELTA' && typeof event.data.payload.text === 'string')
            streaming += event.data.payload.text;
          if (
            [
              'ASSISTANT_MESSAGE_COMPLETED',
              'TOOL_REQUESTED',
              'TOOL_RESULT',
              'RUN_FAILED',
              'RUN_CANCELLED',
              'RUN_TIMED_OUT',
            ].includes(kind)
          ) {
            await query.invalidateQueries({ queryKey: ['conversation-items', id] });
            streaming = '';
          }
          const status = statusFromEvent(event.data);
          if (status) {
            await query.invalidateQueries({ queryKey: ['conversation-runs', id] });
            void invalidateConversation(query, projectId, id);
          }
          if (kind === 'RUN_COMPLETED') {
            await query.invalidateQueries({ queryKey: ['messages', id] });
            streaming = '';
          }
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        const status = (reason as { status?: number }).status;
        if (status === 401 || status === 403 || status === 404) {
          error = explain(reason);
          accessDeniedId = id;
          streaming = '';
          exportRunId = '';
          for (const key of [
            ['conversation-items', id],
            ['conversation-runs', id],
            conversationKeys.detail(id),
          ]) {
            await query.cancelQueries({ queryKey: key });
            query.removeQueries({ queryKey: key });
          }
          await query.invalidateQueries({ queryKey: ['project', projectId] });
          return;
        }
        connection = 'Disconnected; reconnecting…';
      }
      if (!controller.signal.aborted)
        delay = setTimeout(() => void consume(), Math.min(1000 * 2 ** attempt++, 15000));
    }
    void query.invalidateQueries({ queryKey: ['conversation-items', id] });
    void query.invalidateQueries({ queryKey: ['conversation-runs', id] });
    void consume();
    return () => {
      controller.abort();
      if (delay) clearTimeout(delay);
    };
  });
  async function send(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !conversationId || !executionEnabled) return;
    busy = true;
    error = '';
    const submittedMessage = chatDraft.message;
    try {
      await collaborative?.flush();
      if (useProjectFiles && repository) {
        await repository.enableConversation(projectId, conversationId);
        await query.invalidateQueries({
          queryKey: ['conversation-repository', projectId, conversationId],
        });
      }
      const body = {
        content_md: submittedMessage.trim(),
        context_artifact_ids: ids(artifactIds),
        provider_connection_id: providerConnectionId,
      };
      const serialized = JSON.stringify(body);
      if (chatDraft.request?.body !== serialized)
        chatDraft.request = { key: crypto.randomUUID(), body: serialized };
      const result = await agents.queueTurn(conversationId, {
        ...body,
        client_request_id: chatDraft.request.key,
      });
      run = result.run;
      void invalidateConversation(query, projectId, conversationId);
      await query.invalidateQueries({ queryKey: ['conversation-runs', conversationId] });
      if (chatDraft.message === submittedMessage) chatDraft.message = '';
      chatDraft.request = undefined;
      await query.invalidateQueries({ queryKey: ['conversation-items', conversationId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  async function stopAgent() {
    if (run) await stopRun(run);
  }
  async function stopRun(target: Pick<AgentRun, 'id' | 'status' | 'can_interrupt'>) {
    if (!target.can_interrupt || !conversationId || busy || target.status === 'CANCELLING') return;
    busy = true;
    error = '';
    try {
      const cancelled = await agents.cancelRun(conversationId, target.id);
      if (run?.id === target.id) run = cancelled;
      void invalidateConversation(query, projectId, conversationId);
      void query.invalidateQueries({ queryKey: ['conversation-runs', conversationId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  function threadHeaderPortal(node: HTMLElement, active: boolean) {
    if (collaborative || basicFiles) return chatPanelPortal(node, active);
  }
</script>

{#snippet harnessIcon(codex: boolean)}
  {#if codex}<span class="chat-harness-icon chat-harness-icon-codex" aria-hidden="true"></span>
  {:else}<Sparkles class="chat-harness-icon" aria-hidden="true" />{/if}
{/snippet}

{#snippet harnessModelPicker(newConversation: boolean)}
  {@const label = (
    newConversation ? harness === 'codex' : $conversation.data?.configuration?.harness === 'codex'
  )
    ? 'Codex'
    : 'Base'}
  {@const model = availableConnections.find((connection) => connection.id === providerConnectionId)}
  {@const modelLabel =
    model && 'default_for' in model && model.default_for.includes('project_chat')
      ? 'Default'
      : (model?.display_name ?? 'Choose model')}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger
      type="button"
      class="chat-model-trigger"
      aria-label="Choose harness and model"
      title={`${label} · ${(model && 'catalog_id' in model ? model.display_name : model?.model_id) ?? 'Choose model'}`}
      disabled={newConversation ? Boolean(chatDraft.startingConversationId) : Boolean(active)}
    >
      {@render harnessIcon(label === 'Codex')}
      <span class="sr-only">{label}: </span>
      <span class="chat-model-name">{modelLabel}</span>
      <ChevronDown class="size-3" aria-hidden="true" />
    </DropdownMenu.Trigger>
    <DropdownMenu.Content side="top" align="end" sideOffset={8} class="chat-model-menu">
      <DropdownMenu.Label>Harness</DropdownMenu.Label>
      {#if newConversation}
        <DropdownMenu.RadioGroup bind:value={harness}>
          <DropdownMenu.RadioItem value="platform"
            >{@render harnessIcon(false)} Base</DropdownMenu.RadioItem
          >
          <DropdownMenu.RadioItem value="codex"
            >{@render harnessIcon(true)} Codex{!hostedAvailable
              ? ' · unavailable'
              : ''}</DropdownMenu.RadioItem
          >
        </DropdownMenu.RadioGroup>
      {:else}
        <div class="chat-model-fixed">{label}<small>Fixed for this conversation</small></div>
      {/if}
      <DropdownMenu.Separator />
      {#if sharedModels.length}
        <DropdownMenu.Label>Polycolab models</DropdownMenu.Label>
        <DropdownMenu.RadioGroup bind:value={providerConnectionId}>
          {#each sharedModels as model (model.id)}
            <DropdownMenu.RadioItem value={model.id}>
              <span class="chat-model-option"
                ><span>{model.display_name}</span><small>{model.model_id}</small></span
              >
            </DropdownMenu.RadioItem>
          {/each}
        </DropdownMenu.RadioGroup>
        <DropdownMenu.Separator />
      {/if}
      <DropdownMenu.Label>Your connections</DropdownMenu.Label>
      <DropdownMenu.RadioGroup bind:value={providerConnectionId}>
        {#each personalConnections as connection (connection.id)}
          <DropdownMenu.RadioItem value={connection.id}>
            <span class="chat-model-option"
              ><span>{connection.model_id}</span><small>{connection.display_name}</small></span
            >
          </DropdownMenu.RadioItem>
        {/each}
      </DropdownMenu.RadioGroup>
      {#if !availableConnections.length}<p class="chat-model-empty">
          No model connections yet.
        </p>{/if}
      {#if $connections.hasNextPage}<DropdownMenu.Item
          onSelect={(event) => {
            event.preventDefault();
            void $connections.fetchNextPage();
          }}>Load more providers</DropdownMenu.Item
        >{/if}
      <DropdownMenu.Separator />
      <DropdownMenu.Item onclick={() => goto('/settings/provider-connections')}
        >Manage model connections</DropdownMenu.Item
      >
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/snippet}

{#snippet downloadFiles()}
  <Popover.Root>
    <Popover.Trigger
      type="button"
      class="chat-files-trigger"
      disabled={!$exports.data?.length}
      aria-label="Generated files"
    >
      Files{#if $exports.data?.length}
        · {$exports.data.length}{/if}
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content
        side="top"
        align="end"
        sideOffset={8}
        class="chat-files-popover"
        role="dialog"
        aria-label="Generated files"
      >
        <strong>Generated files</strong>
        <p>
          Downloads from {exportRunId ? 'the selected' : 'the latest completed'} run. These are separate
          from project files.
        </p>
        {#each $exports.data ?? [] as file (file.artifact_id)}
          <Button
            variant="outline"
            onclick={() => downloadExport(file.artifact_id, file.display_name)}
            >Download {file.display_name}</Button
          >
        {/each}
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>
{/snippet}

<FeedbackToast
  message={$available.isError ? explain($available.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $available.refetch() }}
/>
<FeedbackToast
  message={$connections.isError ? explain($connections.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $connections.refetch() }}
/>
<FeedbackToast
  message={$conversations.isError ? explain($conversations.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $conversations.refetch() }}
/>
<FeedbackToast
  message={$messages.isError ? explain($messages.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $messages.refetch() }}
/>
<FeedbackToast
  message={$exports.isError ? explain($exports.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $exports.refetch() }}
/>

{#if conversationId && !currentWorktreeId && $repositoryState.data?.enabled && hostedAvailable}
  <div class="conversation-repository-controls">
    {#if $conversationRepository.data?.enabled}
      <a
        href={`/projects/${projectId}/files?branch=${encodeURIComponent($conversationRepository.data.branch || 'main')}`}
        >Review saved agent files</a
      >
      <p class="muted">
        This conversation uses a saved working copy. Files are shared with project members; chat
        stays private.
      </p>
    {:else}
      <label
        ><input type="checkbox" bind:checked={useProjectFiles} disabled={busy} /> Use project files for
        this conversation</label
      >
    {/if}
  </div>
{/if}

<div
  class="project-chat"
  class:project-chat-detail={Boolean(conversationId)}
  class:project-chat-new={!conversationId && !allConversations}
>
  <FeedbackToast pending={busy} message={error} variant="error" />
  {#if !conversationId}
    {#if allConversations}<header class="project-chat-intro">
        <h1>All conversations</h1>
      </header>{/if}
    {#if !allConversations}<ChatComposer
        bind:value={chatDraft.message}
        label="Message the agent"
        onsubmit={create}
        disabled={Boolean(newChatSendReason)}
        sendReason={newChatSendReason === 'Write a message to send.' ? '' : newChatSendReason}
        prompts={promptStarters}
      >
        {#snippet contextControls()}
          {#if !worktreeId && $repositoryState.data?.enabled && hostedAvailable}
            <label
              ><input type="checkbox" bind:checked={useProjectFiles} disabled={busy} /> Use project files
              (saved changes are shared with members)</label
            >
          {/if}
        {/snippet}
        {#snippet preset()}{@render harnessModelPicker(true)}{/snippet}
      </ChatComposer>
      {#if $connections.hasNextPage}<Button
          type="button"
          variant="ghost"
          onclick={() => $connections.fetchNextPage()}>Load more providers</Button
        >{/if}
      {#if !$connections.isPending && !$connections.isError && !availableConnections.length}
        <p role="status">
          Add a provider connection to send messages. <a href="/settings/provider-connections"
            >Set up an AI provider</a
          >
        </p>
      {/if}
    {/if}
    {#if allConversations}<section
        class="project-chat-history"
        aria-label={allConversations ? 'All conversations' : 'Recent conversations'}
      >
        <h2>{allConversations ? 'Conversations' : 'Recent conversations'}</h2>
        <ul class="list">
          {#each ($conversations.data?.pages.flatMap((p) => p.items) ?? []).slice(0, allConversations ? undefined : 5) as value (value)}<li
            >
              <h3>
                <a href={`/projects/${projectId}/conversations/${value.id}`}
                  >{value.title || `${value.configuration?.display_name} conversation`}</a
                >
              </h3>
              <small>{value.status} · {new Date(value.updated_at).toLocaleString()}</small>
            </li>{/each}
        </ul>
        {#if $conversations.isPending}<LoadingState>Loading conversations…</LoadingState
          >{:else if $conversations.isError && !$conversations.data}
          <Button type="submit" onclick={() => $conversations.refetch()}>Retry</Button
          >{:else if !$conversations.data?.pages[0].items.length}<p class="empty">
            No conversations yet. Choose an agent to begin.
          </p>{/if}{#if allConversations && $conversations.hasNextPage}<Button
            type="submit"
            onclick={() => $conversations.fetchNextPage()}>Load more conversations</Button
          >{/if}
      </section>{/if}
  {:else if accessDeniedId === conversationId}<p role="status">
      Conversation access is no longer available.
    </p>
  {:else if $conversation.isPending}<LoadingState>
      Opening conversation…
    </LoadingState>{:else if ($conversation.isError && !$conversation.data) || $conversation.data?.project_id !== projectId}<FeedbackToast
      message="Conversation unavailable. Return to the conversation list."
      variant="error"
    />{:else}
    <header class="project-chat-thread-header" use:threadHeaderPortal={isVisible}>
      {#if !collaborative && !basicFiles}<a href={`/projects/${projectId}/conversations`}
          >← All conversations</a
        >{/if}
      <h1>{$conversation.data?.title || $conversation.data?.configuration?.display_name}</h1>
      {#if $conversation.data?.capabilities.can_manage || $conversation.data?.capabilities.can_share}
        <details class="chat-header-actions">
          <summary aria-label="Conversation actions" title="Conversation actions">•••</summary>
          <div class="chat-header-action-menu">
            {#if $conversation.data?.capabilities.can_manage}
              <Button
                variant="outline"
                onclick={() => {
                  titleDraft = $conversation.data?.title || '';
                  editingTitle = true;
                }}>Rename</Button
              >
              <Button
                variant="outline"
                onclick={async () => {
                  try {
                    await agents.updateConversation(conversationId!, {
                      archived: $conversation.data?.status !== 'archived',
                    });
                    await invalidateConversation(query, projectId, conversationId);
                  } catch (reason) {
                    error = explain(reason);
                  }
                }}
                >{$conversation.data?.status === 'archived'
                  ? 'Restore conversation'
                  : 'Archive conversation'}</Button
              >
            {/if}
            {#if $conversation.data?.capabilities.can_share}<Button
                variant="outline"
                onclick={async () => {
                  try {
                    while ($messages.hasNextPage) {
                      await $messages.fetchNextPage();
                      await tick();
                    }
                    sharingMode =
                      $conversation.data?.sharing === 'private'
                        ? 'members_can_view'
                        : $conversation.data!.sharing;
                    sharing = true;
                  } catch (reason) {
                    error = explain(reason);
                  }
                }}>Sharing</Button
              >{/if}
          </div>
        </details>
      {/if}
      {#if editingTitle}<form
          onsubmit={async (event) => {
            event.preventDefault();
            try {
              await agents.updateConversation(conversationId!, {
                title: titleDraft.trim() || null,
              });
              editingTitle = false;
              await invalidateConversation(query, projectId, conversationId);
            } catch (reason) {
              error = explain(reason);
            }
          }}
        >
          <Field.Label
            >Conversation title<Input bind:value={titleDraft} maxlength={300} /></Field.Label
          >
          <Button type="submit">Save title</Button>
          <Button variant="outline" onclick={() => (editingTitle = false)}>Cancel</Button>
        </form>{/if}
      {#if sharing}<section class="share-preview" aria-label="Preview shared conversation">
          <h2>Share this conversation</h2>
          <Field.Label
            >Project access<NativeSelect bind:value={sharingMode}>
              <option value="private">Private · only me</option>
              <option value="members_can_view">Members can view</option>
              <option value="members_can_participate">Members can participate</option>
            </NativeSelect></Field.Label
          >
          <p>
            Project sharing includes this full transcript and future messages. Editors use their own
            provider connections when participation is enabled. Private prompts, tool inputs, and
            artifacts keep their existing permissions.
          </p>
          {#each $messages.data?.pages.flatMap((p) => p.items) ?? [] as item (item.id)}
            <ConversationTranscriptItem
              {item}
              ownerId={$conversation.data?.owner_id}
              agentName={$conversation.data?.configuration?.display_name}
            />
          {/each}
          <Button
            onclick={async () => {
              try {
                await agents.shareConversation(conversationId!, sharingMode);
                sharing = false;
                await invalidateConversation(query, projectId, conversationId);
              } catch (reason) {
                error = explain(reason);
              }
            }}>Save sharing</Button
          >
          <Button variant="outline" onclick={() => (sharing = false)}>Cancel</Button>
        </section>{/if}
      <FeedbackToast
        message={collaborative && $conversation.data?.working_context.worktree_id
          ? 'This conversation began in Git mode. New turns use the collaborative project; earlier snapshots remain in the Git archive.'
          : ''}
        variant="info"
      />
      {#if $conversation.data?.origin === 'legacy_direct'}<p>
          Retired direct-chat history · Read only
        </p>{:else if !$conversation.data?.capabilities.can_send}<p>
          Shared conversation · View only
        </p>{/if}
    </header>
    <div class="project-chat-panel-meta" use:chatPanelPortal={isVisible}>
      <h2>Conversation</h2>
      <p>{run?.status ? run.status.toLowerCase().replaceAll('_', ' ') : connection}</p>
      {#if $conversation.data?.configuration?.harness === 'codex'}
        <p>Codex</p>
        {#if $conversation.data.configuration?.system_prompt_override}<details>
            <summary>System prompt</summary>
            <p class="project-chat-saved-prompt">
              {$conversation.data.configuration?.system_prompt_override}
            </p>
          </details>{/if}
      {/if}
    </div>
    {#if $messages.isError}
      <Button type="submit" onclick={() => $messages.refetch()}>Retry messages</Button>{/if}
    <ConversationTranscript
      items={$messages.data?.pages.flatMap((p) => p.items) ?? []}
      ownerId={$conversation.data?.owner_id}
      viewerId={$viewer.data?.id}
      agentName={$conversation.data?.configuration?.display_name}
    />
    {#if $messages.hasNextPage}<Button
        type="submit"
        variant="outline"
        class=""
        onclick={() => $messages.fetchNextPage()}>Load more messages</Button
      >{/if}
    {#if active || busy || connection.startsWith('Disconnected')}
      <div class="chat-run-status" role="status" aria-live="polite">
        <LoaderCircle
          size={16}
          class="animate-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
        <span
          >{connection.startsWith('Disconnected')
            ? 'Reconnecting to your conversation…'
            : busy
              ? 'Sending your message…'
              : run?.status === 'QUEUED'
                ? 'Queued · waiting for an available runner'
                : run?.status === 'CLAIMED'
                  ? 'Starting the agent…'
                  : run?.status === 'CANCELLING'
                    ? 'Stopping…'
                    : streaming
                      ? 'Writing a response…'
                      : 'Working on your request…'}</span
        >
      </div>
    {/if}
    {#if streaming}<article class="message">
        <p class="message-author">Agent · responding</p>
        <div class="message-body"><Markdown content={streaming} /></div>
      </article>{/if}
    {#if $conversation.data?.origin === 'agent'}<details
        class="project-chat-files"
        use:chatPanelPortal={isVisible}
      >
        <summary>Files and run history</summary>
        {#if $runRepository.data?.input_commit}
          <p>Project input: <code>{$runRepository.data.input_commit.slice(0, 12)}</code></p>
          <p>
            Saved output: <code
              >{($runRepository.data.output_revision || $runRepository.data.output_commit)?.slice(
                0,
                12,
              ) ?? 'Not saved'}</code
            >
          </p>
        {/if}
        {#if run?.failure_code?.startsWith('repository_')}
          <FeedbackToast
            message="The project could not be saved. Previously saved commits remain available."
            variant="error"
          />
        {/if}
        <ol aria-label="Execution history">
          {#each $runs.data?.pages.flatMap((page) => page.items) ?? [] as execution (execution.id)}
            <li>
              <span
                >Run {execution.queue_sequence} · {execution.status.toLowerCase()} · {execution.requested_model ||
                  'Unknown model'}</span
              >
              {#if execution.can_interrupt}<Button
                  variant="outline"
                  disabled={busy || execution.status === 'CANCELLING'}
                  onclick={() => stopRun(execution)}>Stop run {execution.queue_sequence}</Button
                >{/if}
            </li>
          {/each}
        </ol>
        <Field.Label
          >Files from completed run<NativeSelect bind:value={exportRunId}>
            <option value="">Latest completed run</option>
            {#each $runs.data?.pages
              .flatMap((p) => p.items)
              .filter((r) => r.status === 'COMPLETED' && r.can_read_private_context) ?? [] as value (value.id)}
              <option value={value.id}
                >{new Date(value.created_at).toLocaleString()} · {value.id.slice(0, 8)}</option
              >
            {/each}
          </NativeSelect></Field.Label
        >
      </details>
    {/if}
    {#if run?.failure_code?.endsWith('resume_required')}
      <FeedbackToast
        message="This run may have reached the provider or changed project files. Review its history before sending another message; a new run may repeat work."
        variant="warning"
      />
    {/if}
    {#if $capabilities.data && !$capabilities.data.execution_available}
      <span class="project-conversation-state">Execution unavailable</span>
    {/if}
    {#if $conversation.data?.capabilities.can_send}<div class="project-chat-reply">
        <ChatComposer
          bind:value={chatDraft.message}
          label={$conversation.data && $conversation.data.sharing !== 'private'
            ? 'Message shared with project'
            : 'Private message'}
          placeholder="Ask a question or describe what you want to do…"
          maxlength={100000}
          onsubmit={send}
          onstop={active && run?.can_interrupt ? stopAgent : undefined}
          stopping={run?.status === 'CANCELLING'}
          stopDisabled={busy}
          disabled={Boolean(conversationSendReason)}
          sendReason={run?.status === 'CANCELLING'
            ? 'Stopping agent…'
            : active
              ? ''
              : conversationSendReason === 'Write a message to send.'
                ? ''
                : conversationSendReason}
          submitLabel="Send message"
        >
          {#snippet preset()}
            {@render downloadFiles()}
            {@render harnessModelPicker(false)}
          {/snippet}
          {#snippet contextControls()}
            <div class="project-chat-side-controls" use:chatPanelPortal={isVisible}>
              {#if $connections.hasNextPage}<Button
                  type="button"
                  onclick={() => $connections.fetchNextPage()}>Load more providers</Button
                >{/if}<a href="/settings/provider-connections">Manage provider connections</a>
              <details class="project-chat-settings">
                <summary>Artifact context · {ids(artifactIds).length} files</summary>
                <p>Enter up to 32 artifact IDs from this project to include their metadata.</p>
                <Field.Label
                  >Artifact IDs (comma or whitespace separated)<Textarea
                    bind:value={artifactIds}
                  /></Field.Label
                >
              </details>
            </div>
          {/snippet}
        </ChatComposer>
      </div>{:else}
      {@render downloadFiles()}
      <p role="status">
        {$conversation.data?.origin === 'legacy_direct'
          ? 'This saved direct-chat history cannot execute new messages.'
          : $conversation.data?.status === 'archived'
            ? 'This conversation is archived.'
            : 'You have read-only access to this conversation.'}
      </p>
      {#if active && run?.can_interrupt}<Button
          variant="outline"
          disabled={busy}
          onclick={stopAgent}>Stop run</Button
        >{/if}
    {/if}
  {/if}
</div>
