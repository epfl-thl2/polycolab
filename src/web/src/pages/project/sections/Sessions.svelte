<script lang="ts">
  import { Checkbox } from '../../../lib/components/ui/checkbox';
  import LoadingState from '../../../ui/LoadingState.svelte';
  import FeedbackToast from '../../../ui/FeedbackToast.svelte';
  import * as Field from '../../../lib/components/ui/field';
  import * as DropdownMenu from '../../../lib/components/ui/dropdown-menu';
  import { NativeSelect } from '../../../lib/components/ui/native-select';
  import { Button } from '../../../lib/components/ui/button';
  import { Textarea } from '../../../lib/components/ui/textarea';
  import { Input } from '../../../lib/components/ui/input';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { projectContext, explain } from '../../../svelte-lib/context';
  import { advancesCursor, statusFromEvent } from '../../../svelte-lib/session-events';
  import type { AgentRun } from '../../../lib/agent-sessions-api';
  import { prepareTurn, type TurnDraft } from '../../../lib/run-authority';
  import Markdown from '../../../ui/Markdown.svelte';
  import ChatComposer from '../../../ui/ChatComposer.svelte';
  import { ChevronDown, RotateCcw, SlidersHorizontal, Sparkles } from '@lucide/svelte';
  import { Popover } from 'bits-ui';
  import { chatPanelPortal } from '../../../lib/chat-panel-portal';
  import { chatDrafts, ChatDrafts, chatDraftKey } from '../../../lib/chat-drafts.svelte';
  import {
    createProjectSessions,
    sessionOptions,
    sessionKeys,
    invalidateSession,
  } from '../../../lib/session-queries';
  import { tick, untrack } from 'svelte';
  let {
    projectId,
    sessionId,
    worktreeId,
    view,
    isVisible = true,
    draftKey,
    onCreated,
  }: {
    projectId: string;
    sessionId?: string;
    worktreeId?: string;
    view?: 'chat' | 'list';
    isVisible?: boolean;
    draftKey?: string;
    onCreated?: (id: string) => void;
  } = $props();
  const allSessions = $derived(view ? view === 'list' : page.url.pathname.endsWith('/sessions'));
  const { api, agents, query, records, capabilities: applicationCapabilities } = projectContext();
  const executionEnabled = $derived(applicationCapabilities?.enabled('agent_execution') ?? false);
  const repository = projectContext().repository;
  const linear = projectContext().linear;
  const defaultFiles = projectContext().defaultFiles;
  let useProjectFiles = $state(false);
  const repositoryState = createQuery(
    toStore(() => ({
      queryKey: ['project-repository-availability', projectId],
      enabled: Boolean(repository),
      queryFn: () => repository!.state(projectId),
    })),
  );
  const sessionRepository = createQuery(
    toStore(() => ({
      queryKey: ['session-repository', projectId, sessionId],
      enabled: Boolean(repository && sessionId && $repositoryState.data?.enabled),
      queryFn: () => repository!.session(projectId, sessionId!),
    })),
  );
  let agentId = $state('');
  let profileId = $state('');
  let configurationMode = $state<'preset' | 'custom'>('preset');
  let customSystemPrompt = $state('');
  let customizationOpen = $state(false);
  let contextScope = $state('project');
  let responseStyle = $state('balanced');
  let sharing = $state(false);
  const draftStore = chatDrafts() ?? new ChatDrafts();
  const entryKey = untrack(
    () =>
      draftKey ??
      chatDraftKey(
        projectId,
        sessionId
          ? `/projects/${projectId}/sessions/${sessionId}`
          : page.url.pathname + page.url.search,
      ),
  );
  const chatDraft = untrack(() => draftStore.get(entryKey));
  let reconciliationLoaded = false;
  $effect(() => {
    if (!linear || reconciliationLoaded || typeof location === 'undefined') return;
    const id = new URL(location.href).searchParams.get('reconcile');
    if (!id) return;
    reconciliationLoaded = true;
    void linear.api.batches(projectId).then((batches) => {
      const batch = batches.find((value) => value.id === id && value.status === 'pending');
      if (batch)
        chatDraft.message =
          'Please reconcile this pending file result with the current shared workspace. Preserve newer human changes, review the original and proposed contents below, and validate the combined result.\n\n' +
          JSON.stringify(batch.changes);
    });
  });
  const promptStarters = [
    'Summarize this project',
    'Find related research objects',
    'Help me test a conjecture',
    'Review a proof idea',
    'Suggest next steps',
  ];
  let selected = $state<string[]>([]);
  let destination = $state<TurnDraft['destination']>('REVIEW');
  let publicSelected = $state<string[]>([]);
  let artifactIds = $state('');
  let targets = $state<string[]>([]);
  let extraPublic = $state('');
  let extraTargets = $state('');
  let editable = $state('');
  let operations = $state<TurnDraft['operations']>(['CREATE_RECORD']);
  let maxMutations = $state(10);
  let maxContentBytes = $state(100000);
  const ids = (text: string) => [...new Set(text.split(/[\s,]+/).filter(Boolean))];
  let busy = $state(false);
  let error = $state('');
  let connection = $state('Connecting…');
  let run = $state<Pick<AgentRun, 'id' | 'status'> & { failure_code?: string | null }>();
  let exportRunId = $state('');
  const runRepository = createQuery(
    toStore(() => ({
      queryKey: ['run-repository', projectId, exportRunId || run?.id, run?.status],
      enabled: Boolean(repository && $sessionRepository.data?.enabled && (exportRunId || run?.id)),
      queryFn: () => repository!.run(projectId, exportRunId || run!.id),
    })),
  );
  let streaming = $state('');
  let streamSessionId: string | undefined;
  let streamCursor: string | undefined;
  const sessions = createProjectSessions(
    agents,
    () => projectId,
    () => allSessions,
  );
  const session = createQuery(toStore(() => sessionOptions(agents, sessionId, isVisible)));
  const tasks = projectContext().tasks;
  const currentTaskId = $derived(sessionId ? $session.data?.task_id : worktreeId);
  const task = createQuery(
    toStore(() => ({
      queryKey: ['project-task', projectId, currentTaskId],
      enabled: Boolean(tasks && currentTaskId),
      queryFn: () => tasks!.get(projectId, currentTaskId!),
      refetchInterval: isVisible && currentTaskId ? 5000 : false,
    })),
  );
  const runs = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['session-runs', sessionId],
      enabled: Boolean(sessionId),
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listRuns(sessionId!, pageParam),
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
  const exports = createQuery(
    toStore(() => ({
      queryKey: ['run-artifacts', exportRunId],
      enabled: Boolean(exportRunId),
      queryFn: () => agents.listArtifacts(exportRunId),
    })),
  );
  async function downloadExport(id: string, name: string) {
    try {
      const blob = await agents.downloadArtifact(exportRunId, id);
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
  const profiles = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['profiles'],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listGatewayProfiles(pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const objects = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['objects', projectId],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listObjects(projectId, false, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const messages = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['messages', sessionId],
      enabled: Boolean(sessionId),
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listMessages(sessionId!, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const available = createQuery(
    toStore(() => ({ queryKey: ['agents'], queryFn: () => agents.listAgents() })),
  );
  const availableAgents = $derived($available.data?.items ?? []);
  const availableProfiles = $derived(
    $profiles.data?.pages.flatMap((profilePage) => profilePage.items) ?? [],
  );
  const selectedAgent = $derived(availableAgents.find((agent) => agent.id === agentId));
  const hasCustomSettings = $derived(
    configurationMode === 'custom' || contextScope !== 'project' || responseStyle !== 'balanced',
  );
  $effect(() => {
    if (!agentId && availableAgents[0]) agentId = availableAgents[0].id;
  });
  $effect(() => {
    if (!sessionId && !allSessions && !profileId && availableProfiles[0])
      profileId = availableProfiles[0].id;
  });
  function agentDescription(kind: string) {
    if (kind === 'RESEARCHER') return 'Explore research questions and develop approaches.';
    if (kind === 'CRITIC') return 'Review arguments, evidence, and possible gaps.';
    return 'Use this platform agent for the conversation.';
  }
  function setCustomConfiguration(enabled: boolean) {
    configurationMode = enabled ? 'custom' : 'preset';
  }
  function resetNewChatSettings() {
    agentId = availableAgents[0]?.id ?? '';
    profileId = availableProfiles[0]?.id ?? '';
    configurationMode = 'preset';
    customSystemPrompt = '';
    contextScope = 'project';
    responseStyle = 'balanced';
    customizationOpen = false;
  }
  const pins = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['references', projectId],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        records.references(projectId, pageParam),
      getNextPageParam: (page: { next_cursor: string | null }) => page.next_cursor ?? undefined,
    })),
  );
  const active = $derived(
    run && ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(run.status),
  );
  const newChatSendReason = $derived.by(() => {
    if (busy) return 'Sending…';
    if (worktreeId && $task.isPending) return 'Opening worktree…';
    if (worktreeId && $task.isError) return 'This worktree is unavailable.';
    if ($task.data?.archived_at) return 'This worktree is archived.';
    if (!executionEnabled) return 'Hosted execution is disabled.';
    if (configurationMode === 'custom' && !hostedAvailable) return 'Hosted Codex is unavailable.';
    if (!agentId) return 'Choose a preset below.';
    if (!profileId) return 'Choose an AI provider.';
    if (configurationMode === 'custom' && !customSystemPrompt.trim())
      return 'Add a system prompt in Customize.';
    if (!chatDraft.message.trim()) return 'Write a message to send.';
    return '';
  });
  const newChatVisibleSendReason = $derived(
    newChatSendReason === 'Choose an AI provider.' ? '' : newChatSendReason,
  );
  const sessionSendReason = $derived.by(() => {
    if ($session.data?.can_control === false) return 'This shared conversation is view-only.';
    if (busy) return 'Working…';
    if ($task.data?.archived_at) return 'This worktree is archived.';
    if ($session.data?.status === 'ARCHIVED') return 'This session is archived.';
    if (!executionEnabled) return 'Hosted execution is disabled.';
    if (!$capabilities.data?.execution_available) return 'Agent execution is unavailable.';
    if (active) return 'Wait for the current run to finish.';
    if (!profileId) return 'Choose an AI provider in Chat settings.';
    if (
      destination === 'PUBLIC' &&
      (linear || defaultFiles || useProjectFiles || $sessionRepository.data?.enabled)
    )
      return 'Project files are private. Choose a private contribution destination for this session.';
    if (!(destination === 'PUBLIC' ? chatDraft.publicTask.trim() : chatDraft.message.trim()))
      return destination === 'PUBLIC' ? 'Write a public task to send.' : 'Write a message to send.';
    return '';
  });
  async function create(event: SubmitEvent) {
    event.preventDefault();
    if (
      busy ||
      (worktreeId && ($task.isPending || $task.isError || $task.data?.archived_at)) ||
      !executionEnabled ||
      !chatDraft.message.trim() ||
      !profileId ||
      (configurationMode === 'custom' && (!hostedAvailable || !customSystemPrompt.trim()))
    )
      return;
    busy = true;
    error = '';
    const submittedMessage = chatDraft.message;
    try {
      const choice = $available.data?.items.find((agent) => agent.id === agentId);
      if (!choice || (choice.version !== 1 && choice.version !== 2))
        throw new Error('Choose an available agent version.');
      if (!chatDraft.startingSessionId) {
        const created = await agents.createSession({
          project_id: projectId,
          ...(worktreeId ? { worktree_id: worktreeId } : {}),
          agent_kind: choice.agent_kind,
          agent_version: choice.version,
          ...(configurationMode === 'custom'
            ? { harness: 'codex' as const, system_prompt: customSystemPrompt.trim() }
            : {}),
        });
        query.setQueryData(sessionKeys.detail(created.id), created);
        chatDraft.startingSessionId = created.id;
        await invalidateSession(query, projectId);
      }
      if (!worktreeId && useProjectFiles && repository)
        await repository.enableSession(projectId, chatDraft.startingSessionId);
      const body = {
        ...prepareTurn({
          destination: 'REVIEW',
          privateMessage: submittedMessage,
          publicTask: '',
          privateRevisions: [],
          privateArtifacts: [],
          publicRevisions: [],
          publicTargets: [],
          operations: ['CREATE_RECORD'],
          editableObjects: [],
          maxMutations: 10,
          maxContentBytes: 100000,
        }),
        gateway_profile_id: profileId,
      };
      const serialized = JSON.stringify(body);
      if (chatDraft.startRequest?.body !== serialized)
        chatDraft.startRequest = { key: crypto.randomUUID(), body: serialized };
      await linear?.flush();
      await agents.queueTurn(chatDraft.startingSessionId, {
        ...body,
        client_request_id: chatDraft.startRequest.key,
      });
      if (chatDraft.message === submittedMessage) chatDraft.message = '';
      if (chatDraft.message) {
        const savedKey = chatDraftKey(
          projectId,
          `/projects/${projectId}/sessions/${chatDraft.startingSessionId}`,
        );
        draftStore.get(savedKey).message = chatDraft.message;
      }
      draftStore.delete(entryKey);
      void invalidateSession(query, projectId, chatDraft.startingSessionId);
      if (onCreated) onCreated(chatDraft.startingSessionId);
      else await goto(`/projects/${projectId}/sessions/${chatDraft.startingSessionId}`);
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  $effect(() => {
    const id = sessionId;
    if (!isVisible || !id || !$session.data || $session.data.project_id !== projectId) return;
    if (streamSessionId !== id) {
      streamSessionId = id;
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
          if (kind === 'ASSISTANT_MESSAGE_COMPLETED') {
            await query.invalidateQueries({ queryKey: ['messages', id] });
            streaming = '';
          }
          const status = statusFromEvent(event.data);
          if (status) {
            await query.invalidateQueries({ queryKey: ['session-runs', id] });
            void invalidateSession(query, projectId, id);
          }
          if (kind === 'RUN_COMPLETED') {
            await query.invalidateQueries({ queryKey: ['messages', id] });
            await query.invalidateQueries({ queryKey: ['proposals', projectId] });
            await query.invalidateQueries({ queryKey: ['objects', projectId] });
            await query.invalidateQueries({ queryKey: ['records', projectId] });
            await query.invalidateQueries({ queryKey: ['object', projectId] });
            streaming = '';
          }
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        const status = (reason as { status?: number }).status;
        if (status === 401 || status === 403 || status === 404) {
          error = explain(reason);
          query.removeQueries({ queryKey: ['messages', id] });
          await query.invalidateQueries({ queryKey: ['project', projectId] });
          return;
        }
        connection = 'Disconnected; reconnecting…';
      }
      if (!controller.signal.aborted)
        delay = setTimeout(() => void consume(), Math.min(1000 * 2 ** attempt++, 15000));
    }
    void query.invalidateQueries({ queryKey: ['messages', id] });
    void query.invalidateQueries({ queryKey: ['session-runs', id] });
    void consume();
    return () => {
      controller.abort();
      if (delay) clearTimeout(delay);
    };
  });
  async function send(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !sessionId || !executionEnabled) return;
    busy = true;
    error = '';
    const submittedMessage = chatDraft.message;
    const submittedPublicTask = chatDraft.publicTask;
    const submittedDestination = destination;
    try {
      await linear?.flush();
      if (useProjectFiles && repository) {
        await repository.enableSession(projectId, sessionId);
        await query.invalidateQueries({ queryKey: ['session-repository', projectId, sessionId] });
      }
      const body = {
        ...prepareTurn({
          destination: $session.data?.agent_version === 2 ? submittedDestination : 'REVIEW',
          privateMessage: submittedMessage,
          publicTask: submittedPublicTask,
          privateRevisions: selected,
          privateArtifacts: ids(artifactIds),
          publicRevisions: [...publicSelected, ...ids(extraPublic)],
          publicTargets: [...targets, ...ids(extraTargets)],
          operations,
          editableObjects: ids(editable),
          maxMutations,
          maxContentBytes,
        }),
        gateway_profile_id: profileId,
      };
      const serialized = JSON.stringify(body);
      if (chatDraft.request?.body !== serialized)
        chatDraft.request = { key: crypto.randomUUID(), body: serialized };
      const result = await agents.queueTurn(sessionId, {
        ...body,
        client_request_id: chatDraft.request.key,
      });
      run = result.run;
      void invalidateSession(query, projectId, sessionId);
      await query.invalidateQueries({ queryKey: ['session-runs', sessionId] });
      if (submittedDestination === 'PUBLIC') {
        if (chatDraft.publicTask === submittedPublicTask) chatDraft.publicTask = '';
      } else if (chatDraft.message === submittedMessage) chatDraft.message = '';
      chatDraft.request = undefined;
      await query.invalidateQueries({ queryKey: ['messages', sessionId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  async function stopAgent() {
    if (!run || busy || run.status === 'CANCELLING') return;
    busy = true;
    error = '';
    try {
      run = await agents.cancelRun(run.id);
      void invalidateSession(query, projectId, sessionId);
      void query.invalidateQueries({ queryKey: ['session-runs', sessionId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
  function threadHeaderPortal(node: HTMLElement, active: boolean) {
    if (linear || defaultFiles) return chatPanelPortal(node, active);
  }
</script>

<FeedbackToast
  message={$available.isError ? explain($available.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $available.refetch() }}
/>
<FeedbackToast
  message={$profiles.isError ? explain($profiles.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $profiles.refetch() }}
/>
<FeedbackToast
  message={$sessions.isError ? explain($sessions.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $sessions.refetch() }}
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
<FeedbackToast
  message={$pins.isError ? explain($pins.error) : ''}
  variant="error"
  action={{ label: 'Retry', run: () => $pins.refetch() }}
/>

{#if sessionId && !currentTaskId && $repositoryState.data?.enabled && hostedAvailable}
  <div class="session-repository-controls">
    {#if $sessionRepository.data?.enabled}
      <a
        href={`/projects/${projectId}/files?branch=${encodeURIComponent($sessionRepository.data.branch || 'main')}`}
        >Review saved agent files</a
      >
      <p class="muted">
        This session uses a saved working copy. Files are shared with project members; chat stays
        private.
      </p>
    {:else}
      <label
        ><input type="checkbox" bind:checked={useProjectFiles} disabled={busy} /> Use project files for
        this session</label
      >
    {/if}
  </div>
{/if}

<div
  class="project-chat"
  class:project-chat-detail={Boolean(sessionId)}
  class:project-chat-new={!sessionId && !allSessions}
>
  <span class="project-execution-state" aria-label="Execution status"
    >{executionEnabled ? 'Execution available' : 'Execution disabled'}</span
  >
  <FeedbackToast pending={busy} message={error} variant="error" />
  {#if !sessionId}
    {#if allSessions}<header class="project-chat-intro">
        <h1>All sessions</h1>
      </header>{/if}
    {#if !allSessions}<ChatComposer
        bind:value={chatDraft.message}
        label="Message the agent"
        onsubmit={create}
        disabled={Boolean(newChatSendReason)}
        sendReason={newChatVisibleSendReason}
        prompts={promptStarters}
      >
        {#snippet configuration()}
          <Popover.Root bind:open={customizationOpen}>
            <Popover.Trigger
              type="button"
              class="project-chat-customize-trigger"
              aria-label="Customize chat"
              disabled={Boolean(chatDraft.startingSessionId)}
            >
              <SlidersHorizontal class="size-4" aria-hidden="true" />
              <span>{hasCustomSettings ? 'Custom' : 'Customize'}</span>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                side="top"
                align="end"
                sideOffset={10}
                class="project-chat-customization-popover"
                role="dialog"
                aria-label="Customize chat"
              >
                <header class="project-chat-customization-header">
                  <h2>Customize chat</h2>
                  <p>
                    {selectedAgent
                      ? agentDescription(selectedAgent.agent_kind)
                      : 'Configure this conversation.'}
                  </p>
                </header>
                <div class="project-chat-customization-fields">
                  <Field.Label
                    >Context scope<NativeSelect
                      aria-label="Context scope"
                      bind:value={contextScope}
                      disabled={Boolean(chatDraft.startingSessionId)}
                    >
                      <option value="project">Entire project</option>
                      <option value="selected">Selected research</option>
                      <option value="custom">Custom scope</option>
                    </NativeSelect></Field.Label
                  >
                  <Field.Label
                    >Response style<NativeSelect
                      aria-label="Response style"
                      bind:value={responseStyle}
                      disabled={Boolean(chatDraft.startingSessionId)}
                    >
                      <option value="balanced">Balanced</option>
                      <option value="concise">Concise</option>
                      <option value="detailed">Detailed</option>
                    </NativeSelect></Field.Label
                  >
                  <a href="/settings/model-providers">Manage AI providers</a>
                  <button
                    type="button"
                    class="project-chat-custom-toggle"
                    aria-pressed={configurationMode === 'custom'}
                    disabled={Boolean(chatDraft.startingSessionId)}
                    onclick={() => setCustomConfiguration(configurationMode !== 'custom')}
                  >
                    <span>
                      <strong>Custom instructions</strong>
                      <small>Add a session-specific system prompt through Hosted Codex.</small>
                    </span>
                    <span class="project-chat-custom-toggle-state"
                      >{configurationMode === 'custom' ? 'On' : 'Off'}</span
                    >
                  </button>
                  {#if configurationMode === 'custom'}
                    {#if !hostedAvailable}
                      <p class="project-chat-unavailable" role="status">
                        Hosted Codex is unavailable right now. You can review these options, but
                        cannot start a customized chat.
                      </p>
                    {/if}
                    <Field.Label
                      >System prompt<Textarea
                        required
                        aria-label="System prompt"
                        placeholder="Give the agent instructions for this chat…"
                        maxlength={10000}
                        bind:value={customSystemPrompt}
                        disabled={Boolean(chatDraft.startingSessionId)}
                      /></Field.Label
                    >
                    <p class="muted project-chat-config-help">
                      Added to the base agent instructions for this session.
                    </p>
                    <Field.Label
                      >Harness<NativeSelect aria-label="Harness" value="codex" disabled>
                        <option value="codex">Hosted Codex</option>
                      </NativeSelect></Field.Label
                    >
                  {/if}
                </div>
                <footer class="project-chat-customization-footer">
                  <Button
                    type="button"
                    variant="ghost"
                    class="project-chat-reset"
                    disabled={Boolean(chatDraft.startingSessionId)}
                    onclick={resetNewChatSettings}
                    ><RotateCcw class="size-4" aria-hidden="true" />Reset to defaults</Button
                  >
                </footer>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        {/snippet}
        {#snippet contextControls()}
          {#if !worktreeId && $repositoryState.data?.enabled && hostedAvailable}
            <label
              ><input type="checkbox" bind:checked={useProjectFiles} disabled={busy} /> Use project files
              (saved changes are shared with members)</label
            >
          {/if}
        {/snippet}
        {#snippet preset()}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger
              type="button"
              class="project-chat-agent-trigger"
              aria-label="Choose agent"
              disabled={Boolean(chatDraft.startingSessionId) || !availableAgents.length}
            >
              <Sparkles class="size-4" aria-hidden="true" />
              <span class="project-chat-agent-trigger-copy">
                <strong>{selectedAgent?.display_name ?? 'Loading agents…'}</strong>
                {#if selectedAgent}<small>v{selectedAgent.version}</small>{/if}
              </span>
              <ChevronDown class="size-3" aria-hidden="true" />
            </DropdownMenu.Trigger>
            <DropdownMenu.Content
              side="top"
              align="end"
              sideOffset={8}
              class="project-chat-agent-menu"
            >
              <DropdownMenu.Label>Choose an agent</DropdownMenu.Label>
              <DropdownMenu.Separator />
              <DropdownMenu.RadioGroup bind:value={agentId}>
                {#each availableAgents as agent (agent.id)}
                  <DropdownMenu.RadioItem value={agent.id} class="project-chat-agent-option">
                    <span class="project-chat-agent-option-icon">
                      <Sparkles class="size-4" aria-hidden="true" />
                    </span>
                    <span class="project-chat-agent-option-copy">
                      <span>
                        <strong>{agent.display_name}</strong>
                        <small>v{agent.version}</small>
                      </span>
                      <small>{agentDescription(agent.agent_kind)}</small>
                    </span>
                  </DropdownMenu.RadioItem>
                {/each}
              </DropdownMenu.RadioGroup>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        {/snippet}
      </ChatComposer>
    {/if}
    {#if allSessions}<section
        class="project-chat-history"
        aria-label={allSessions ? 'All sessions' : 'Recent sessions'}
      >
        <h2>{allSessions ? 'Sessions' : 'Recent sessions'}</h2>
        <ul class="list">
          {#each ($sessions.data?.pages.flatMap((p) => p.items) ?? []).slice(0, allSessions ? undefined : 5) as value (value)}<li
            >
              <h3>
                <a href={`/projects/${projectId}/sessions/${value.id}`}
                  >{value.title || `${value.agent_display_name} session`}</a
                >
              </h3>
              <small>{value.status} · {new Date(value.updated_at).toLocaleString()}</small>
            </li>{/each}
        </ul>
        {#if $sessions.isPending}<LoadingState>Loading sessions…</LoadingState
          >{:else if $sessions.isError && !$sessions.data}
          <Button type="submit" onclick={() => $sessions.refetch()}>Retry</Button
          >{:else if !$sessions.data?.pages[0].items.length}<p class="empty">
            No sessions yet. Choose an agent to begin.
          </p>{/if}{#if allSessions && $sessions.hasNextPage}<Button
            type="submit"
            onclick={() => $sessions.fetchNextPage()}>Load more sessions</Button
          >{/if}
      </section>{/if}
  {:else if $session.isPending}<LoadingState>
      Opening session…
    </LoadingState>{:else if ($session.isError && !$session.data) || $session.data?.project_id !== projectId}<FeedbackToast
      message="Session unavailable. Return to the session list."
      variant="error"
    />{:else}
    <header class="project-chat-thread-header" use:threadHeaderPortal={isVisible}>
      {#if !linear && !defaultFiles}<a href={`/projects/${projectId}/sessions`}>← All sessions</a
        >{/if}
      <h1>{$session.data?.title || $session.data?.agent_display_name}</h1>
      {#if (linear || defaultFiles) && $session.data?.can_control !== false}<Button
          variant="outline"
          onclick={async () => {
            try {
              if ($session.data?.is_shared) {
                if (
                  confirm(
                    'Make this chat private again? Already viewed content cannot be recalled.',
                  )
                ) {
                  await agents.shareSession(sessionId!, false);
                  await invalidateSession(query, projectId, sessionId);
                }
              } else {
                while ($messages.hasNextPage) {
                  await $messages.fetchNextPage();
                  await tick();
                }
                sharing = true;
              }
            } catch (reason) {
              error = explain(reason);
            }
          }}>{$session.data?.is_shared ? 'Make private' : 'Share with project'}</Button
        >{/if}
      {#if sharing}<section class="share-preview" aria-label="Preview shared conversation">
          <h2>Share this conversation</h2>
          <p>
            All project members, including readers, will see this entire transcript and future
            messages. Only you can send messages or control runs. Attachments keep their existing
            permissions.
          </p>
          {#each $messages.data?.pages.flatMap((p) => p.items) ?? [] as message (message.id)}<article
            >
              <strong>{message.role === 'USER' ? 'You' : 'Agent'}</strong><Markdown
                content={message.content_md}
              />
            </article>{/each}<Button
            onclick={async () => {
              try {
                await agents.shareSession(sessionId!, true);
                sharing = false;
                await invalidateSession(query, projectId, sessionId);
              } catch (reason) {
                error = explain(reason);
              }
            }}>Share full conversation and future messages</Button
          ><Button variant="outline" onclick={() => (sharing = false)}>Cancel</Button>
        </section>{/if}
      <FeedbackToast
        message={linear && $session.data?.worktree_id
          ? 'This conversation began in Git mode. New turns use the linear project; earlier snapshots remain in the Git archive.'
          : ''}
        variant="info"
      />
      {#if $session.data?.can_control === false}<p>Shared conversation · View only</p>{/if}
    </header>
    <div class="project-chat-panel-meta" use:chatPanelPortal={isVisible}>
      <h2>Session</h2>
      <p role="status">{run?.status ?? connection}</p>
      {#if $session.data?.harness === 'codex'}
        <p>Hosted Codex</p>
        <details>
          <summary>System prompt</summary>
          <p class="project-chat-saved-prompt">{$session.data.system_prompt}</p>
        </details>
      {/if}
    </div>
    {#if $messages.isError}
      <Button type="submit" onclick={() => $messages.refetch()}>Retry messages</Button>{/if}
    <div class="transcript">
      {#each $messages.data?.pages.flatMap((p) => p.items) ?? [] as message (message.id)}<article
          class={`message ${message.role === 'USER' ? 'user' : ''}`}
        >
          <p class="message-author">
            {message.role === 'USER'
              ? $session.data?.can_control === false
                ? 'Chat owner'
                : 'You'
              : $session.data?.agent_display_name}
          </p>
          <div class="message-body"><Markdown content={message.content_md} /></div>
        </article>{/each}
    </div>
    {#if $messages.hasNextPage}<Button
        type="submit"
        variant="outline"
        class=""
        onclick={() => $messages.fetchNextPage()}>Load more messages</Button
      >{/if}
    {#if streaming}<article class="message">
        <p class="message-author">Agent · responding</p>
        <p class="message-stream">{streaming}</p>
      </article>{/if}
    {#if $session.data?.can_control !== false}<details
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
        <Field.Label
          >Files from completed run<NativeSelect bind:value={exportRunId}>
            <option value="">Choose a completed run</option>
            {#each $runs.data?.pages
              .flatMap((p) => p.items)
              .filter((r) => r.status === 'COMPLETED') ?? [] as value (value.id)}
              <option value={value.id}
                >{new Date(value.created_at).toLocaleString()} · {value.id.slice(0, 8)}</option
              >
            {/each}
          </NativeSelect></Field.Label
        >

        {#if $exports.data?.length}
          <div aria-label="Session files">
            {#each $exports.data as file (file.artifact_id)}
              <Button onclick={() => downloadExport(file.artifact_id, file.display_name)}>
                Download {file.display_name}
              </Button>
            {/each}
          </div>
        {/if}
      </details>
    {/if}
    {#if run?.failure_code?.endsWith('resume_required')}
      <FeedbackToast
        message="This run may have reached the provider or changed research. Review its history before sending another message; a new run may repeat work."
        variant="warning"
      />
    {/if}
    {#if $capabilities.data && !$capabilities.data.execution_available}
      <span class="project-session-state">Execution unavailable</span>
    {/if}
    {#if $session.data?.can_control !== false}<div class="project-chat-reply">
        <ChatComposer
          bind:value={
            () => (destination === 'PUBLIC' ? chatDraft.publicTask : chatDraft.message),
            (value) => {
              if (destination === 'PUBLIC') chatDraft.publicTask = value;
              else chatDraft.message = value;
            }
          }
          label={destination === 'PUBLIC'
            ? 'Separate public task'
            : $session.data?.is_shared
              ? 'Message shared with project'
              : 'Private message'}
          placeholder={destination === 'PUBLIC'
            ? 'Describe the public contribution task…'
            : 'Ask a question or describe what you want to do…'}
          maxlength={destination === 'PUBLIC' ? 20000 : 100000}
          onsubmit={send}
          onstop={active ? stopAgent : undefined}
          stopping={run?.status === 'CANCELLING'}
          stopDisabled={busy}
          disabled={Boolean(sessionSendReason)}
          sendReason={run?.status === 'CANCELLING'
            ? 'Stopping agent…'
            : active
              ? ''
              : sessionSendReason === 'Write a message to send.' ||
                  sessionSendReason === 'Write a public task to send.'
                ? ''
                : sessionSendReason}
          submitLabel={destination === 'PUBLIC'
            ? 'Authorize public contribution run'
            : 'Send message'}
        >
          {#snippet preset()}
            <span class="project-chat-reply-agent"
              ><Sparkles size={16} aria-hidden="true" />{$session.data?.agent_display_name}</span
            >
          {/snippet}
          {#snippet contextControls()}
            <div class="project-chat-side-controls" use:chatPanelPortal={isVisible}>
              <Field.Label
                >AI provider<NativeSelect required bind:value={profileId}
                  ><option value="">Choose an AI provider</option
                  >{#each $profiles.data?.pages.flatMap((p) => p.items) ?? [] as profile (profile.id)}<option
                      value={profile.id}>{profile.display_name} · {profile.model_id}</option
                    >{/each}</NativeSelect
                ></Field.Label
              >{#if $profiles.hasNextPage}<Button
                  type="button"
                  onclick={() => $profiles.fetchNextPage()}>Load more providers</Button
                >{/if}<a href="/settings/model-providers">Manage AI providers</a>
              <details class="project-chat-settings">
                <summary>Run settings</summary>
                <details>
                  <summary>Context · {selected.length} pinned versions</summary>
                  <p class="muted">Only these exact versions are selected for this turn.</p>
                  {#each $objects.data?.pages.flatMap((p) => p.items) ?? [] as object (object.id)}<Field.Label
                      class="row mb-3"
                      ><Checkbox
                        checked={selected.includes(object.current_object_version_id)}
                        onCheckedChange={(checked) => {
                          selected = checked
                            ? [...selected, object.current_object_version_id]
                            : selected.filter((item) => item !== object.current_object_version_id);
                        }}
                        value={object.current_object_version_id}
                      />{object.current_object_version.content.title} · r{object
                        .current_object_version.number}</Field.Label
                    >{/each}{#if $objects.hasNextPage}<Button
                      type="button"
                      onclick={() => $objects.fetchNextPage()}>Load more context</Button
                    >{/if}
                </details>
                {#if destination !== 'PUBLIC'}<details>
                    <summary>Artifact context · {ids(artifactIds).length} exact IDs</summary>
                    <p>
                      Enter at most 32 exact committed artifact IDs. The service rechecks project
                      access and exposes bounded metadata only; neighboring artifacts and object
                      bytes are not implied.
                    </p>
                    <Field.Label
                      >Exact committed artifact IDs (comma or whitespace separated)<Textarea
                        bind:value={artifactIds}
                      ></Textarea></Field.Label
                    >
                  </details>{:else}<p class="muted">
                    Private artifact selections are retained locally and are not sent with a public
                    turn.
                  </p>{/if}
                <details>
                  <summary>Public research inputs</summary>
                  <p>
                    Choose exact public versions. Project pins are never automatically upgraded.
                  </p>
                  {#each $pins.data?.pages.flatMap((page) => page.items) ?? [] as pin (pin.id)}
                    {#if pin.available}<Field.Label
                        ><Checkbox
                          checked={publicSelected.includes(pin.object_version_id)}
                          onCheckedChange={(checked) => {
                            publicSelected = checked
                              ? [...publicSelected, pin.object_version_id]
                              : publicSelected.filter((item) => item !== pin.object_version_id);
                          }}
                          value={pin.object_version_id}
                        />{pin.title} · {pin.object_version_id}</Field.Label
                      >
                    {:else}<p>Unavailable public source (not selectable)</p>{/if}
                  {/each}
                  {#if $pins.isError}<Button type="button" onclick={() => $pins.refetch()}
                      >Retry pins</Button
                    >{/if}
                  {#if $pins.hasNextPage}<Button type="button" onclick={() => $pins.fetchNextPage()}
                      >Load more public pins</Button
                    >{/if}
                  <Field.Label
                    >Additional public version IDs (comma or whitespace separated)<Textarea
                      bind:value={extraPublic}
                    ></Textarea></Field.Label
                  >
                </details>
                {#if $session.data?.agent_version === 2}
                  <fieldset disabled={busy || active || !executionEnabled}>
                    <legend>Authority for this turn</legend>
                    <Field.Label
                      >Contribution destination<NativeSelect bind:value={destination}>
                        <option value="REVIEW"
                          >Private conversation and reviewed proposals only</option
                        >
                        <option value="PROJECT">Direct contributions to this private project</option
                        >
                        <option
                          value="PUBLIC"
                          disabled={useProjectFiles || $sessionRepository.data?.enabled}
                          >Direct contributions to explicit public targets</option
                        >
                      </NativeSelect></Field.Label
                    >
                    {#if destination !== 'REVIEW'}
                      <p>
                        Requested rights are intersected with current permissions on every tool
                        call. Catalogue admission and official edits remain human-only.
                      </p>
                      {#each ['CREATE_RECORD', 'REVISE_RECORD', 'CREATE_RELATION'] as const as operation (operation)}
                        <Field.Label
                          ><Checkbox
                            checked={operations.includes(operation)}
                            onCheckedChange={(checked) => {
                              operations = checked
                                ? [...operations, operation]
                                : operations.filter((item) => item !== operation);
                            }}
                            value={operation}
                          />{operation}</Field.Label
                        >
                      {/each}
                      {#if operations.includes('REVISE_RECORD')}
                        <Field.Label
                          >Editable research object IDs<Textarea bind:value={editable}
                          ></Textarea></Field.Label
                        >
                        <p>
                          Pin each record's exact input version. Only records you can delegate
                          editing may be listed; use a suggestion for other records.
                        </p>
                      {/if}
                      <Field.Label
                        >Maximum mutations<Input
                          type="number"
                          min="1"
                          max="50"
                          required
                          bind:value={maxMutations}
                        /></Field.Label
                      >
                      <Field.Label
                        >Maximum content bytes per mutation<Input
                          type="number"
                          min="1"
                          max="500000"
                          required
                          bind:value={maxContentBytes}
                        /></Field.Label
                      >
                    {/if}
                    {#if destination === 'PUBLIC'}
                      <p class="notice">
                        This run uses only the separate public task and public research inputs. Your
                        private conversation and private version selections are excluded. Do not put
                        private information in the public task.
                      </p>
                      {#each $pins.data?.pages.flatMap((page) => page.items) ?? [] as pin (pin.id)}
                        {#if pin.available}<Field.Label
                            ><Checkbox
                              checked={targets.includes(pin.object_version_id)}
                              onCheckedChange={(checked) => {
                                targets = checked
                                  ? [...targets, pin.object_version_id]
                                  : targets.filter((item) => item !== pin.object_version_id);
                              }}
                              value={pin.object_version_id}
                            />Public contribution target: {pin.title}</Field.Label
                          >{/if}
                      {/each}
                      <Field.Label
                        >Additional exact public target version IDs<Textarea
                          bind:value={extraTargets}
                        ></Textarea></Field.Label
                      >
                      <p>
                        Public targets are also explicitly pinned as inputs. Public contributions
                        are visible immediately; they are not verified results.
                      </p>
                    {/if}
                  </fieldset>
                {/if}
              </details>
            </div>
            {#if destination === 'PUBLIC'}<p class="project-chat-public-notice">
                This sends a public task. Your private message draft stays private and is not
                included.
              </p>{/if}
          {/snippet}
        </ChatComposer>
      </div>{:else}<p role="status">
        Shared conversation · only its creator can send messages or control runs.
      </p>{/if}
  {/if}
</div>
