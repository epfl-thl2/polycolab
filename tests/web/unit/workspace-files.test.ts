import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import WorkspaceFiles from '../../../web/src/ui/WorkspaceFiles.svelte';
import { contextKey } from '../../../web/src/svelte-lib/context';
import { encodeFile } from '../../../web/src/lib/repository-api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup() {
  const api = {
    state: vi.fn().mockResolvedValue({
      enabled: true,
      writable: true,
      branch: 'main',
      commit: 'a'.repeat(40),
      branches: { main: 'a'.repeat(40) },
      files: [{ path: 'note.md', size: 4, executable: false }],
    }),
    file: vi.fn().mockResolvedValue({ content_base64: encodeFile('base') }),
    save: vi.fn(),
  };
  const { component } = render(WorkspaceFiles, {
    props: { projectId: 'workspace' },
    context: new Map([[contextKey, { repository: api }]]),
  });
  return { ...api, component };
}

it('protects drafts when changing working copies, including a failed branch read', async () => {
  const api = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'note.md' }));
  await fireEvent.input(screen.getByLabelText('File contents'), {
    target: { value: 'unsaved task work' },
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  api.state.mockClear();
  expect(await api.component.selectWorkspaceBranch('tasks/next')).toBe(false);
  expect(api.state).not.toHaveBeenCalled();
  expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe(
    'unsaved task work',
  );
  confirm.mockReturnValue(true);
  api.state.mockRejectedValueOnce(new Error('Temporary storage outage'));
  await expect(api.component.selectWorkspaceBranch('tasks/next')).rejects.toThrow(
    'Temporary storage outage',
  );
  expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe(
    'unsaved task work',
  );
  expect(await api.component.selectWorkspaceBranch('tasks/next')).toBe(true);
  await waitFor(() => expect(screen.queryByLabelText('File contents')).toBeNull());
  expect(api.state).toHaveBeenLastCalledWith('workspace', 'tasks/next');
});

it('rejects exported file selection during a pending save and permits it after completion', async () => {
  const api = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'note.md' }));
  const noteId = screen.getByRole('tab', { name: /note.md/ }).id.replace('file-tab-', '');
  await fireEvent.click(screen.getByRole('button', { name: 'New file' }));
  await fireEvent.input(screen.getByLabelText('File path'), { target: { value: 'draft.md' } });
  await fireEvent.input(screen.getByLabelText('File contents'), {
    target: { value: 'pending draft' },
  });
  let completeSave!: (value: { commit: string }) => void;
  api.save.mockReturnValue(
    new Promise((resolve) => {
      completeSave = resolve;
    }),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.save).toHaveBeenCalledOnce());
  expect(api.component.selectWorkspaceFile(noteId)).toBe(false);
  expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe(
    'pending draft',
  );
  completeSave({ commit: 'b'.repeat(40) });
  await screen.findByText('Saved.');
  await waitFor(() => expect(api.component.selectWorkspaceFile(noteId)).toBe(true));
  await waitFor(() =>
    expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe('base'),
  );
});

it('retains a stale draft and explicitly rebases it on the latest saved version', async () => {
  const api = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'note.md' }));
  const editor = await screen.findByLabelText('File contents');
  await fireEvent.input(editor, { target: { value: 'my draft' } });
  api.save.mockRejectedValueOnce({ status: 409, code: 'repository_stale_save' });
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await screen.findByRole('alert');
  expect((editor as HTMLTextAreaElement).value).toBe('my draft');
  api.state.mockResolvedValue({
    enabled: true,
    writable: true,
    branch: 'main',
    commit: 'b'.repeat(40),
    branches: { main: 'b'.repeat(40) },
    files: [{ path: 'note.md', size: 5, executable: false }],
  });
  // Failed writes preserve the old expected commit and retry key.
  api.save.mockRejectedValueOnce({ status: 409, code: 'repository_stale_save' });
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(2));
  expect(api.save.mock.calls[1]![2]).toBe(api.save.mock.calls[0]![2]);
  // Polling sees the collaborator's save without replacing the draft.
  await waitFor(
    () =>
      expect(screen.getByText('Shared files changed since you opened this draft.')).toBeTruthy(),
    { timeout: 6500 },
  );
  expect((editor as HTMLTextAreaElement).value).toBe('my draft');
  api.file.mockResolvedValue({ content_base64: encodeFile('theirs') });
  await fireEvent.click(screen.getByRole('button', { name: 'Compare latest saved file' }));
  await screen.findByText('theirs');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Keep my draft and use this version as its base' }),
  );
  api.save.mockResolvedValue({ commit: 'c'.repeat(40) });
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(3));
  expect(api.save.mock.calls[2]![1]).toMatchObject({
    expected_commit: 'b'.repeat(40),
    changes: [{ path: 'note.md', content_base64: encodeFile('my draft') }],
  });
});

it('keeps drafts in separate tabs and asks only when closing an unsaved tab', async () => {
  setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'New file' }));
  await fireEvent.input(screen.getByLabelText('File path'), { target: { value: 'idea.md' } });
  await fireEvent.input(screen.getByLabelText('File contents'), { target: { value: 'unsaved' } });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  await fireEvent.click(screen.getByRole('button', { name: 'note.md' }));
  await waitFor(() =>
    expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe('base'),
  );
  expect(confirm).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole('tab', { name: /idea.md/ }));
  expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe('unsaved');
  await fireEvent.click(screen.getByRole('button', { name: 'Close idea.md' }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole('tab', { name: /idea.md/ })).toBeTruthy();
  confirm.mockReturnValue(true);
  await fireEvent.click(screen.getByRole('button', { name: 'Close idea.md' }));
  expect(screen.queryByRole('tab', { name: /idea.md/ })).toBeNull();
});

it('saves the current tab with the keyboard without discarding a draft in another tab', async () => {
  const api = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'note.md' }));
  await fireEvent.input(screen.getByLabelText('File contents'), {
    target: { value: 'changed note' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'New file' }));
  await fireEvent.input(screen.getByLabelText('File path'), { target: { value: 'proof.md' } });
  await fireEvent.input(screen.getByLabelText('File contents'), {
    target: { value: 'draft proof' },
  });
  await fireEvent.click(screen.getByRole('tab', { name: /note.md/ }));
  api.save.mockResolvedValue({ commit: 'b'.repeat(40) });
  api.state.mockResolvedValue({
    enabled: true,
    writable: true,
    branch: 'main',
    commit: 'b'.repeat(40),
    branches: { main: 'b'.repeat(40) },
    files: [{ path: 'note.md', size: 12, executable: false }],
  });
  api.file.mockResolvedValue({ content_base64: encodeFile('changed note') });
  await fireEvent.keyDown(window, { key: 's', ctrlKey: true });
  await screen.findByText('Saved.');
  await waitFor(() =>
    expect((screen.getByRole('tab', { name: /proof.md/ }) as HTMLButtonElement).disabled).toBe(
      false,
    ),
  );
  await fireEvent.click(screen.getByRole('tab', { name: /proof.md/ }));
  expect((screen.getByLabelText('File contents') as HTMLTextAreaElement).value).toBe('draft proof');
  await fireEvent.keyDown(window, { key: 's', metaKey: true });
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(2));
  expect(api.save.mock.calls[1]![1]).toMatchObject({
    expected_commit: 'b'.repeat(40),
    changes: [{ path: 'proof.md', content_base64: encodeFile('draft proof') }],
  });
});

it('can compare and save a new file after a collaborator advances the shared copy', async () => {
  const api = setup();
  await fireEvent.click(await screen.findByRole('button', { name: 'New file' }));
  await fireEvent.input(screen.getByLabelText('File path'), { target: { value: 'new.md' } });
  await fireEvent.input(screen.getByLabelText('File contents'), {
    target: { value: 'my new note' },
  });
  api.state.mockResolvedValue({
    enabled: true,
    writable: true,
    branch: 'main',
    commit: 'b'.repeat(40),
    branches: { main: 'b'.repeat(40) },
    files: [],
  });
  await waitFor(
    () => expect(screen.getByRole('button', { name: 'Compare latest saved file' })).toBeTruthy(),
    { timeout: 6500 },
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Compare latest saved file' }));
  await screen.findByText('[No saved file at this path]');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Keep my draft and use this version as its base' }),
  );
  api.save.mockResolvedValue({ commit: 'c'.repeat(40) });
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(api.save).toHaveBeenCalled());
  expect(api.save.mock.calls[0]![1]).toMatchObject({
    expected_commit: 'b'.repeat(40),
    changes: [{ path: 'new.md', content_base64: encodeFile('my new note') }],
  });
});
