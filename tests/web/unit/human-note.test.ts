import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import HumanNote from '../../../src/web/src/ui/HumanNote.svelte';
import type { HumanNoteView } from '../../../src/web/src/lib/research-structure-view';

afterEach(cleanup);

const note: HumanNoteView = {
  ownerId: 'ada-user',
  owner: 'Ada',
  canEdit: false,
  current: {
    revisionId: 'note-r2',
    content: 'Current private context',
    author: 'Ada',
    createdAt: '2026-09-07',
  },
  history: [],
};

it('shows non-owners the private note without an edit control', () => {
  render(HumanNote, { props: { objectId: 'claim', objectTitle: 'Tree claim', note } });

  expect(screen.getByText('Current private context')).toBeTruthy();
  expect(screen.getByText('Only Ada can revise this note.')).toBeTruthy();
  expect(screen.queryByLabelText('Private note')).toBeNull();
  expect(screen.getByText(/never publishable/)).toBeTruthy();
});

it('retains an owner draft through stale comparison and rotates its base deliberately', async () => {
  const save = vi.fn().mockRejectedValueOnce({ status: 409 }).mockResolvedValueOnce({});
  const loadCurrent = vi.fn().mockResolvedValue({
    revisionId: 'note-r3',
    content: 'A newer saved note',
    author: 'Ada',
    createdAt: '2026-09-07',
  });
  render(HumanNote, {
    props: {
      objectId: 'claim',
      objectTitle: 'Tree claim',
      note,
      canEdit: true,
      save,
      loadCurrent,
    },
  });

  const editor = screen.getByLabelText('Private note');
  await fireEvent.input(editor, { target: { value: 'My retained context' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Save private note' }));
  expect((await screen.findByRole('alert')).textContent).toContain('draft is retained');
  expect((editor as HTMLTextAreaElement).value).toBe('My retained context');

  await fireEvent.click(
    screen.getByRole('button', { name: 'Load current saved note for comparison' }),
  );
  expect(await screen.findByText('A newer saved note')).toBeTruthy();
  expect((editor as HTMLTextAreaElement).value).toBe('My retained context');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Use this exact base, retaining my draft' }),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Save private note' }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[0]![0].baseRevisionId).toBe('note-r2');
  expect(save.mock.calls[1]![0].baseRevisionId).toBe('note-r3');
  expect(save.mock.calls[1]![0].content).toBe('My retained context');
});

it('reuses a retry key only while the note body and base are unchanged', async () => {
  const save = vi.fn().mockRejectedValue({ status: 503 });
  render(HumanNote, {
    props: { objectId: 'claim', objectTitle: 'Tree claim', note, canEdit: true, save },
  });
  const editor = screen.getByLabelText('Private note');
  const button = screen.getByRole('button', { name: 'Save private note' });

  await fireEvent.input(editor, { target: { value: 'Draft one' } });
  await fireEvent.click(button);
  await screen.findByRole('alert');
  await fireEvent.click(button);
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1]![1]).toBe(save.mock.calls[0]![1]);

  await fireEvent.input(editor, { target: { value: 'Draft two' } });
  await fireEvent.click(button);
  await waitFor(() => expect(save).toHaveBeenCalledTimes(3));
  expect(save.mock.calls[2]![1]).not.toBe(save.mock.calls[1]![1]);
});
