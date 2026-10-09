import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import WorkspaceTasks from '../../../src/web/src/ui/WorkspaceTasks.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import type { WorkspaceTask } from '../../../src/web/src/lib/workspace-tasks-api';
const task = (id: string, title = 'Prove the bound', archived = false): WorkspaceTask => ({
  id,
  workspace_id: 'workspace',
  title,
  branch: `tasks/${id}`,
  created_by_user_id: 'ada',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  archived_at: archived ? '2026-02-01' : null,
});
const chat = (id: string, taskId: string | null, status = 'SUCCEEDED') => ({
  id,
  task_id: taskId,
  title: `Conversation ${id}`,
  agent_display_name: 'Researcher',
  status: 'ACTIVE',
  updated_at: '2026-01-01',
  latest_run: { id: `run-${id}`, status, cancel_requested_at: null },
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function setup(
  options: Record<string, unknown> = {},
  items = [task('bound'), task('old', 'Old task', true)],
) {
  const tasks = {
    list: vi.fn().mockResolvedValue({ items }),
    create: vi.fn().mockResolvedValue(task('new', 'New proof')),
    update: vi.fn().mockResolvedValue(task('bound', 'Renamed')),
  };
  const agents = {
    listSessions: vi.fn().mockResolvedValue({
      items: [chat('shared', null), chat('bound', 'bound'), chat('old', 'old')],
    }),
    cancelRun: vi.fn().mockResolvedValue({}),
  };
  const onSelectTask = vi.fn().mockResolvedValue(true);
  const onOpenSession = vi.fn();
  const onNewChat = vi.fn();
  const onTasksChange = vi.fn();
  render(WorkspaceTasks, {
    props: {
      projectId: 'workspace',
      onSelectTask,
      onOpenSession,
      onNewChat,
      onTasksChange,
      repositoryEnabled: true,
      canCreate: true,
      canChat: true,
      ...options,
    },
    context: new Map([
      [
        contextKey,
        { tasks, agents, query: { invalidateQueries: vi.fn().mockResolvedValue(undefined) } },
      ],
    ]),
  });
  return { tasks, agents, onSelectTask, onOpenSession, onNewChat, onTasksChange };
}
it('groups own conversations under named tasks and shared workspace, with archived tasks collapsed', async () => {
  const { onOpenSession, onNewChat } = setup();
  await screen.findByRole('button', { name: 'Prove the bound' });
  expect(screen.getByRole('button', { name: /Conversation shared Researcher/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Conversation bound Researcher/ })).toBeNull();
  await fireEvent.click(
    screen.getByRole('button', { name: 'Toggle Prove the bound conversations' }),
  );
  await fireEvent.click(screen.getByRole('button', { name: /Conversation bound Researcher/ }));
  expect(onOpenSession).toHaveBeenCalledWith(
    expect.objectContaining({ id: 'bound', task_id: 'bound' }),
  );
  await fireEvent.click(
    within(screen.getByRole('region', { name: 'Prove the bound' })).getByRole('button', {
      name: 'New conversation',
    }),
  );
  expect(onNewChat).toHaveBeenCalledWith(task('bound'));
  expect(screen.queryByRole('region', { name: 'Old task' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Archived tasks (1)' }));
  expect(screen.getByRole('region', { name: 'Old task' })).toBeTruthy();
});
it('expands a task only after the parent accepts working-copy selection', async () => {
  const { onSelectTask } = setup();
  const select = await screen.findByRole('button', { name: 'Prove the bound' });
  onSelectTask.mockResolvedValueOnce(false);
  await fireEvent.click(select);
  await waitFor(() => expect(onSelectTask).toHaveBeenCalledOnce());
  expect(screen.queryByRole('button', { name: /Conversation bound Researcher/ })).toBeNull();
  await fireEvent.click(select);
  await screen.findByRole('button', { name: /Conversation bound Researcher/ });
});
it('preserves task creation text and retry id, then selects the durable created task', async () => {
  const { tasks, onSelectTask } = setup();
  await fireEvent.click(screen.getByRole('button', { name: 'New task' }));
  await fireEvent.input(screen.getByLabelText('Task name'), { target: { value: 'New proof' } });
  tasks.create.mockRejectedValueOnce(new Error('Temporary failure'));
  await fireEvent.click(screen.getByRole('button', { name: 'Create task' }));
  await screen.findByRole('alert');
  expect((screen.getByLabelText('Task name') as HTMLInputElement).value).toBe('New proof');
  await fireEvent.click(screen.getByRole('button', { name: 'Create task' }));
  await waitFor(() => expect(tasks.create).toHaveBeenCalledTimes(2));
  expect(tasks.create.mock.calls[0]?.[2]).toBe(tasks.create.mock.calls[1]?.[2]);
  await waitFor(() => expect(onSelectTask).toHaveBeenCalledWith(task('new', 'New proof')));
});
it('searches chats across collapsed tasks without hiding shared workspace', async () => {
  setup();
  await screen.findByRole('button', { name: 'Prove the bound' });
  await fireEvent.input(screen.getByLabelText('Search tasks and conversations'), {
    target: { value: 'Conversation bound' },
  });
  expect(screen.getByRole('region', { name: 'Shared workspace' })).toBeTruthy();
  expect(screen.getByRole('button', { name: /Conversation bound Researcher/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Conversation shared Researcher/ })).toBeNull();
});
it('renames tasks and reports archive failures beside their task', async () => {
  const { tasks, onTasksChange } = setup();
  await screen.findByRole('button', { name: 'Prove the bound' });
  await fireEvent.click(
    screen.getByRole('button', { name: 'Toggle Prove the bound conversations' }),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Rename Prove the bound' }));
  await fireEvent.input(screen.getByLabelText('Rename task'), { target: { value: 'Renamed' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
  await screen.findByRole('button', { name: 'Renamed' });
  expect(tasks.update).toHaveBeenCalledWith('workspace', 'bound', { title: 'Renamed' });
  expect(onTasksChange).toHaveBeenCalledWith(expect.arrayContaining([task('bound', 'Renamed')]));
  tasks.update.mockRejectedValueOnce({ code: 'repository_task_active', status: 409 });
  await fireEvent.click(screen.getByRole('button', { name: 'Archive Renamed' }));
  expect((await screen.findByRole('alert')).textContent).toContain('active run');
});
it('keeps shared chats available when file storage is disabled and does not request tasks', async () => {
  const { tasks } = setup({ repositoryEnabled: false, canCreate: false, canChat: false });
  await screen.findByRole('button', { name: /Conversation shared Researcher/ });
  expect(tasks.list).not.toHaveBeenCalled();
  expect((screen.getByRole('button', { name: 'New task' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(screen.queryByRole('button', { name: 'New conversation' })).toBeNull();
});
it('aggregates only loaded own conversations and cancels eligible runs', async () => {
  const { agents } = setup();
  await screen.findByRole('button', { name: 'Prove the bound' });
  agents.listSessions.mockResolvedValue({
    items: [chat('one', 'bound', 'RUNNING'), chat('two', 'bound', 'QUEUED')],
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Refresh tasks' }));
  await screen.findByText('1 running · 1 waiting in your loaded conversations');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Toggle Prove the bound conversations' }),
  );
  expect(
    (screen.getByRole('button', { name: 'Archive Prove the bound' }) as HTMLButtonElement).disabled,
  ).toBe(true);
  await fireEvent.click(screen.getByRole('button', { name: 'Cancel run for Conversation one' }));
  await waitFor(() => expect(agents.cancelRun).toHaveBeenCalledWith('run-one'));
});

it('loads further task and conversation pages without dropping already loaded groups', async () => {
  const { tasks, agents } = setup();
  await screen.findByRole('button', { name: 'Prove the bound' });
  tasks.list.mockResolvedValue({ items: [task('bound')], nextCursor: 'task-next' });
  agents.listSessions.mockResolvedValue({ items: [chat('shared', null)], nextCursor: 'chat-next' });
  await fireEvent.click(screen.getByRole('button', { name: 'Refresh tasks' }));
  await screen.findByRole('button', { name: 'Load more tasks' });
  tasks.list.mockImplementation(async (_id, cursor) =>
    cursor
      ? { items: [task('more', 'Another task')] }
      : { items: [task('bound')], nextCursor: 'task-next' },
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Load more tasks' }));
  await screen.findByRole('button', { name: 'Another task' });
  expect(screen.getByRole('button', { name: 'Prove the bound' })).toBeTruthy();
  agents.listSessions.mockImplementation(async (_id, cursor) =>
    cursor
      ? { items: [chat('more', 'more')] }
      : { items: [chat('shared', null)], nextCursor: 'chat-next' },
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Load more conversations' }));
  await waitFor(() => expect(agents.listSessions).toHaveBeenCalledWith('workspace', 'chat-next'));
  await fireEvent.click(screen.getByRole('button', { name: 'Toggle Another task conversations' }));
  await screen.findByRole('button', { name: /Conversation more Researcher/ });
});

it('shows task working copies to read-only members without requesting private conversations', async () => {
  const { agents } = setup({ canReadChats: false, canCreate: false, canChat: false });
  await screen.findByRole('button', { name: 'Prove the bound' });
  expect(agents.listSessions).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: /Conversation/ })).toBeNull();
  await fireEvent.click(
    screen.getByRole('button', { name: 'Toggle Prove the bound conversations' }),
  );
  expect(screen.queryByRole('button', { name: 'Rename Prove the bound' })).toBeNull();
});

it('shortens UUID working-copy labels while keeping the full branch searchable and available in a tooltip', async () => {
  const id = '77777777-7777-4777-8777-777777777777';
  setup({}, [task(id)]);
  await screen.findByRole('button', { name: 'Prove the bound' });
  expect(screen.getByText('tasks/77777777')).toBeTruthy();
  expect(screen.getByTitle(`tasks/${id}`)).toBeTruthy();
  await fireEvent.input(screen.getByLabelText('Search tasks and conversations'), {
    target: { value: id },
  });
  expect(screen.getByRole('button', { name: 'Prove the bound' })).toBeTruthy();
});
