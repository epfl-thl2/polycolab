import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import WorkspaceWorktrees from '../../../src/web/src/ui/WorkspaceWorktrees.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

const tree = { id: 'proof', title: 'Proof', branch: 'tasks/proof', archived_at: null };
const chat = (id: string, task_id: string | null) => ({
  id,
  task_id,
  title: id,
  agent_display_name: 'Researcher',
  updated_at: '2026-01-01',
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function setup(options = {}) {
  const tasks = {
    list: vi.fn().mockResolvedValue({ items: [tree] }),
    create: vi
      .fn()
      .mockResolvedValue({ ...tree, id: 'new', title: 'Experiment', branch: 'tasks/new' }),
    update: vi.fn(),
  };
  const agents = {
    listSessions: vi.fn().mockResolvedValue({
      items: [chat('General', null), chat('Approach one', 'proof'), chat('Approach two', 'proof')],
    }),
  };
  const onSelectWorktree = vi.fn().mockResolvedValue(true);
  const onOpenSession = vi.fn();
  const onNewChat = vi.fn();
  render(WorkspaceWorktrees, {
    props: {
      projectId: 'workspace',
      repositoryEnabled: true,
      canCreate: true,
      canChat: true,
      canReadChats: true,
      onSelectWorktree,
      onOpenSession,
      onNewChat,
      onWorktreesChange: vi.fn(),
      ...options,
    },
    context: new Map([[contextKey, { tasks, agents }]]),
  });
  return { tasks, agents, onSelectWorktree, onOpenSession, onNewChat };
}
it('groups conversations under Main and their saved worktree without search controls', async () => {
  const { onOpenSession, onNewChat } = setup();
  await screen.findByRole('button', { name: 'Select Proof worktree' });
  expect(
    within(screen.getByRole('region', { name: 'Main worktree' })).getByRole('button', {
      name: /General Researcher/,
    }),
  ).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Approach one Researcher/ })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Toggle Proof conversations' }));
  const group = within(screen.getByRole('region', { name: 'Proof worktree' }));
  await fireEvent.click(group.getByRole('button', { name: /Approach two Researcher/ }));
  expect(onOpenSession).toHaveBeenCalledWith('Approach two');
  await fireEvent.click(group.getByRole('button', { name: 'New conversation in Proof' }));
  expect(onNewChat).toHaveBeenCalledWith(tree);
  expect(screen.queryByRole('textbox')).toBeNull();
});
it('waits for draft protection before expanding a selected worktree', async () => {
  const { onSelectWorktree } = setup();
  const select = await screen.findByRole('button', { name: 'Select Proof worktree' });
  onSelectWorktree.mockResolvedValueOnce(false);
  await fireEvent.click(select);
  await waitFor(() => expect(onSelectWorktree).toHaveBeenCalledOnce());
  expect(screen.queryByRole('button', { name: /Approach one Researcher/ })).toBeNull();
  await fireEvent.click(select);
  await screen.findByRole('button', { name: /Approach one Researcher/ });
});
it('retains the name and retry identity after a failed worktree creation', async () => {
  const { tasks, onSelectWorktree } = setup();
  tasks.create.mockRejectedValueOnce(new Error('Temporary failure'));
  await fireEvent.click(screen.getByRole('button', { name: 'New worktree' }));
  await fireEvent.input(screen.getByLabelText('Worktree name'), {
    target: { value: 'Experiment' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Create worktree' }));
  await screen.findByRole('alert');
  expect((screen.getByLabelText('Worktree name') as HTMLInputElement).value).toBe('Experiment');
  await fireEvent.click(screen.getByRole('button', { name: 'Create worktree' }));
  await waitFor(() =>
    expect(onSelectWorktree).toHaveBeenCalledWith(expect.objectContaining({ title: 'Experiment' })),
  );
  expect(tasks.create.mock.calls[0]).toEqual(tasks.create.mock.calls[1]);
});
it('allows read-only members to inspect worktrees without fetching private chats', async () => {
  const { agents } = setup({ canCreate: false, canChat: false, canReadChats: false });
  await screen.findByRole('button', { name: 'Select Proof worktree' });
  expect(agents.listSessions).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: 'New worktree' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(screen.queryByRole('button', { name: /New conversation in/ })).toBeNull();
});
