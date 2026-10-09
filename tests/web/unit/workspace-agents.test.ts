import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import WorkspaceAgents from '../../../src/web/src/ui/WorkspaceAgents.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const session = (id: string, status = 'RUNNING') => ({
  id,
  title: `Chat ${id}`,
  agent_display_name: 'Researcher',
  status: 'ACTIVE',
  updated_at: id === 'older' ? '2026-01-01' : '2026-02-01',
  latest_run: { id: `run-${id}`, status, cancel_requested_at: null as string | null },
});
function setup(items = [session('recent'), session('older', 'FAILED')]) {
  const agents = {
    listSessions: vi.fn().mockResolvedValue({ items, nextCursor: 'page-2' }),
    cancelRun: vi.fn().mockResolvedValue({}),
  };
  const onOpenSession = vi.fn();
  const onNewChat = vi.fn();
  const query = { invalidateQueries: vi.fn().mockResolvedValue(undefined) };
  render(WorkspaceAgents, {
    props: { projectId: 'workspace', activeSessionId: 'older', onOpenSession, onNewChat },
    context: new Map([[contextKey, { agents, query }]]),
  });
  return { agents, onOpenSession, onNewChat };
}
it('keeps the selected chat first and searches loaded sessions by agent or title', async () => {
  setup();
  await screen.findByRole('button', { name: /Chat recent Researcher running/ });
  const chats = screen
    .getAllByRole('button')
    .filter((button) => button.classList.contains('open-session'));
  expect(chats[0]?.textContent).toContain('Chat older');
  expect(chats[0]?.getAttribute('aria-current')).toBe('true');
  await fireEvent.input(screen.getByLabelText('Search agent sessions'), {
    target: { value: 'recent' },
  });
  expect(screen.queryByRole('button', { name: /Chat older Researcher failed/ })).toBeNull();
});
it('opens chats and delegates resume to the existing chat controls', async () => {
  const { onOpenSession, onNewChat } = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'Resume run for Chat older' }));
  expect(onOpenSession).toHaveBeenCalledWith('older');
  await fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
  expect(onNewChat).toHaveBeenCalledOnce();
});
it('loads the next cursor and keeps cancel failures beside the affected chat', async () => {
  const { agents } = setup();
  await screen.findByRole('button', { name: 'Load more chats' });
  agents.listSessions.mockResolvedValue({ items: [session('next')], nextCursor: undefined });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more chats' }));
  await screen.findByRole('button', { name: /Chat next Researcher running/ });
  expect(agents.listSessions).toHaveBeenLastCalledWith('workspace', 'page-2');
  agents.cancelRun.mockRejectedValue(new Error('Cancel unavailable'));
  await fireEvent.click(screen.getByRole('button', { name: 'Cancel run for Chat next' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Cancel unavailable');
  expect(agents.cancelRun).toHaveBeenCalledWith('run-next');
});
it('shows list failures and supports retry', async () => {
  const { agents } = setup();
  await screen.findByRole('button', { name: /Chat recent Researcher running/ });
  agents.listSessions.mockRejectedValueOnce(new Error('List unavailable'));
  await fireEvent.click(screen.getByRole('button', { name: 'Refresh agent sessions' }));
  await screen.findByRole('alert');
  await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
it('does not offer cancel for an already requested cancellation', async () => {
  setup([
    {
      ...session('recent'),
      latest_run: { id: 'run-recent', status: 'RUNNING', cancel_requested_at: '2026-02-01' },
    },
  ]);
  await screen.findByRole('button', { name: /Chat recent Researcher Cancelling/ });
  expect(screen.queryByRole('button', { name: 'Cancel run for Chat recent' })).toBeNull();
});
