import { runFixture, sessionFixture } from './session-fixtures';
import { QueryClient } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ProjectAgents from '../../../src/web/src/pages/project/components/ProjectAgents.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
});
const session = (id: string, status: ReturnType<typeof runFixture>['status'] = 'RUNNING') =>
  sessionFixture({
    id,
    title: `Chat ${id}`,
    updated_at: id === 'older' ? '2026-01-01' : '2026-02-01',
    latest_execution: runFixture({ id: `run-${id}`, status }),
  });
function setup(
  items: Array<ReturnType<typeof session>> = [session('recent'), session('older', 'FAILED')],
  canReadChats = true,
) {
  const agents = {
    listConversations: vi.fn().mockResolvedValue({ items, nextCursor: 'page-2' }),
    cancelRun: vi.fn().mockResolvedValue({}),
  };
  const onOpenConversation = vi.fn();
  const onNewChat = vi.fn();
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(query);
  render(ProjectAgents, {
    props: {
      projectId: 'project',
      activeConversationId: 'older',
      onOpenConversation,
      onNewChat,
      canReadChats,
    },
    context: new Map([[contextKey, { agents, query }]]),
  });
  return { agents, onOpenConversation, onNewChat };
}
it('shows all conversations by recency without worktree groups or search controls', async () => {
  setup([
    { ...session('recent'), working_context: { worktree_id: 'saved-worktree' } },
    session('older', 'FAILED'),
  ]);
  await screen.findByRole('button', { name: /Chat recent Researcher running/ });
  const chats = screen.getAllByRole('button', { name: /^Chat (recent|older) Researcher/ });
  expect(chats[0]?.textContent).toContain('Chat recent');
  expect(chats[1]?.getAttribute('aria-current')).toBe('true');
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByText('Shared project')).toBeNull();
  expect(screen.queryByRole('button', { name: 'New task' })).toBeNull();
});
it('opens chats and delegates resume to the existing chat controls', async () => {
  const { onOpenConversation, onNewChat } = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'Resume run for Chat older' }));
  expect(onOpenConversation).toHaveBeenCalledWith('older');
  await fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));
  expect(onNewChat).toHaveBeenCalledOnce();
});
it('loads the next cursor and reports cancel failures in a dismissible toast', async () => {
  const { agents } = setup();
  await screen.findByRole('button', { name: 'Load more chats' });
  agents.listConversations.mockResolvedValue({ items: [session('next')], nextCursor: undefined });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more chats' }));
  await screen.findByRole('button', { name: /Chat next Researcher running/ });
  expect(agents.listConversations).toHaveBeenLastCalledWith('project', 'page-2');
  agents.cancelRun.mockRejectedValue(new Error('Cancel unavailable'));
  await fireEvent.click(screen.getByRole('button', { name: 'Cancel run for Chat next' }));
  const failure = await screen.findByRole('alert');
  expect(failure.textContent).toContain('Cancel unavailable');
  expect(failure.closest('[data-feedback-toast]')).toBeTruthy();
  expect(failure.closest('.session')).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(agents.cancelRun).toHaveBeenCalledWith('next', 'run-next');
});
it('shows list failures and supports retry', async () => {
  const { agents } = setup();
  await screen.findByRole('button', { name: /Chat recent Researcher running/ });
  agents.listConversations.mockRejectedValueOnce(new Error('List unavailable'));
  await fireEvent.click(screen.getByRole('button', { name: 'Load more chats' }));
  await screen.findByRole('alert');
  await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
it('does not fetch conversations without project membership', async () => {
  const { agents } = setup([], false);
  expect(agents.listConversations).not.toHaveBeenCalled();
  expect(screen.getByText('Conversations are unavailable for your role.')).toBeTruthy();
});
it('does not offer cancel for an already requested cancellation', async () => {
  setup([
    {
      ...session('recent'),
      latest_execution: {
        ...runFixture(),
        id: 'run-recent',
        status: 'RUNNING',
        cancel_requested_at: '2026-02-01',
      },
    },
  ]);
  await screen.findByRole('button', { name: /Chat recent Researcher Cancelling/ });
  expect(screen.queryByRole('button', { name: 'Cancel run for Chat recent' })).toBeNull();
});
