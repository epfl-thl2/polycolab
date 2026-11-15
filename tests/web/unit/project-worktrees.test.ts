import { conversationFixture } from './conversation-fixtures';
import { QueryClient } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import ProjectWorktrees from '../../../src/web/src/pages/project/components/ProjectWorktrees.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

const tree = { id: 'proof', title: 'Proof', branch: 'worktrees/proof', removed_at: null };
const chat = (id: string, worktree_id: string | null) =>
  conversationFixture({
    id,
    title: id,
    working_context: { worktree_id },
    updated_at: '2026-01-01',
  });
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
});
function setup(options = {}) {
  const worktrees = {
    list: vi.fn().mockResolvedValue({ items: [tree] }),
    create: vi
      .fn()
      .mockResolvedValue({ ...tree, id: 'new', title: 'Experiment', branch: 'worktrees/new' }),
    update: vi.fn(),
  };
  const agents = {
    listConversations: vi.fn().mockResolvedValue({
      items: [chat('General', null), chat('Approach one', 'proof'), chat('Approach two', 'proof')],
    }),
  };
  const onSelectWorktree = vi.fn().mockResolvedValue(true);
  const onOpenConversation = vi.fn();
  const onNewChat = vi.fn();
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(query);
  render(ProjectWorktrees, {
    props: {
      projectId: 'project',
      repositoryEnabled: true,
      canCreate: true,
      canChat: true,
      canReadChats: true,
      onSelectWorktree,
      onOpenConversation,
      onNewChat,
      onWorktreesChange: vi.fn(),
      ...options,
    },
    context: new Map([[contextKey, { worktrees, agents, query }]]),
  });
  return { worktrees, agents, onSelectWorktree, onOpenConversation, onNewChat };
}
it('groups conversations under Main and their saved worktree without search controls', async () => {
  const { onOpenConversation, onNewChat } = setup();
  await screen.findByRole('button', { name: 'Select Proof worktree' });
  expect(
    await within(screen.getByRole('region', { name: 'Main worktree' })).findByRole('button', {
      name: /General Researcher/,
    }),
  ).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Approach one Researcher/ })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Toggle Proof conversations' }));
  const group = within(screen.getByRole('region', { name: 'Proof worktree' }));
  await fireEvent.click(group.getByRole('button', { name: /Approach two Researcher/ }));
  expect(onOpenConversation).toHaveBeenCalledWith('Approach two');
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
  const { worktrees, onSelectWorktree } = setup();
  worktrees.create.mockRejectedValueOnce(new Error('Temporary failure'));
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
  expect(worktrees.create.mock.calls[0]).toEqual(worktrees.create.mock.calls[1]);
});
it('allows read-only members to inspect worktrees without fetching private chats', async () => {
  const { agents } = setup({ canCreate: false, canChat: false, canReadChats: false });
  await screen.findByRole('button', { name: 'Select Proof worktree' });
  expect(agents.listConversations).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: 'New worktree' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(screen.queryByRole('button', { name: /New conversation in/ })).toBeNull();
});
