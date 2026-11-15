import type { components } from '../../../src/web/src/lib/api-client';

type Session = components['schemas']['ConversationRead'];
type Run = components['schemas']['RunRead'];
type Message = components['schemas']['MessageItemRead'];
export const sessionTime = '2026-01-01T00:00:00Z';
export const sessionOwner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

export function sessionFixture(overrides: Partial<Session> = {}): Session {
  const id = overrides.id ?? '44444444-4444-4444-8444-444444444444';
  return {
    id,
    owner_id: sessionOwner,
    project_id: '11111111-1111-1111-1111-111111111111',
    title: null,
    origin: 'agent',
    status: 'active',
    sharing: 'private',
    configuration: {
      agent_version_id: 'agent-1',
      agent_kind: 'RESEARCHER',
      agent_version: 1,
      display_name: 'Researcher',
      harness: 'platform',
      harness_version: null,
      connection_protocol: null,
      system_prompt_override: null,
    },
    working_context: { worktree_id: null },
    hierarchy: {
      root_id: id,
      parent_id: null,
      spawning_run_id: null,
      spawning_item_id: null,
      delegated_task: null,
    },
    created_at: sessionTime,
    updated_at: sessionTime,
    archived_at: null,
    capabilities: { can_send: true, can_manage: true, can_share: true, can_stream: true },
    latest_execution: null,
    usage: null,
    ...overrides,
  };
}

export function runFixture(overrides: Partial<Run> = {}): Run {
  return {
    id: 'run-1',
    conversation_id: '44444444-4444-4444-8444-444444444444',
    project_id: '11111111-1111-1111-1111-111111111111',
    origin: 'agent',
    client_request_id: 'request-1',
    request_item_id: 'message-1',
    parent_run_id: null,
    requested_by_user_id: sessionOwner,
    queue_sequence: 1,
    status: 'QUEUED',
    attempt: 0,
    cancel_requested_at: null,
    deadline_at: null,
    started_at: null,
    finished_at: null,
    failure_code: null,
    created_at: sessionTime,
    updated_at: sessionTime,
    requested_model: 'model',
    observed_model: null,
    usage: null,
    can_interrupt: true,
    can_resume: false,
    can_read_private_context: true,
    ...overrides,
  };
}

export function messageItemFixture(overrides: Partial<Message> = {}): Message {
  return {
    id: 'message-1',
    conversation_id: '44444444-4444-4444-8444-444444444444',
    sequence: 1,
    type: 'message',
    author: { type: 'human', user_id: sessionOwner },
    execution_id: 'run-1',
    created_at: sessionTime,
    status: 'completed',
    data: { role: 'user', content_md: 'Explore this claim.' },
    ...overrides,
  };
}
