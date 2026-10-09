import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import VersionedSourceEditor from '../../../src/web/src/ui/VersionedSourceEditor.svelte';

afterEach(cleanup);

const source = {
  objectId: 'source',
  revisionId: 'source-r2',
  language: 'LEAN' as const,
  content: 'theorem t : True := by trivial',
  href: '/source-r2',
};

it('keeps Monaco lazy and retains a stale source draft through exact-base comparison', async () => {
  const save = vi
    .fn()
    .mockRejectedValueOnce({ status: 409 })
    .mockResolvedValueOnce({ ...source, revisionId: 'source-r4', content: 'draft' });
  const loadCurrent = vi
    .fn()
    .mockResolvedValue({ ...source, revisionId: 'source-r3', content: 'new saved source' });
  render(VersionedSourceEditor, { props: { source, save, loadCurrent } });
  expect(
    screen.getByRole('button', { name: 'Load enhanced code editor' }).getAttribute('aria-pressed'),
  ).toBe('false');
  const editor = screen.getByLabelText('Source code');
  await fireEvent.input(editor, { target: { value: 'draft' } });
  const submit = screen.getByRole('button', { name: 'Save new source version' });
  await fireEvent.click(submit);
  expect((await screen.findByRole('alert')).textContent).toContain('draft is retained');
  await fireEvent.click(screen.getByRole('button', { name: 'Load current source for comparison' }));
  expect(await screen.findByText('new saved source')).toBeTruthy();
  expect((editor as HTMLTextAreaElement).value).toBe('draft');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Use this exact base, retaining my draft' }),
  );
  await fireEvent.click(submit);
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1]![0]).toMatchObject({
    baseRevisionId: 'source-r3',
    content: 'draft',
    language: 'LEAN',
  });
});

it('reports drafts to the parent for navigation-safe storage', async () => {
  const onDraftChange = vi.fn();
  render(VersionedSourceEditor, {
    props: { source, save: vi.fn(), loadCurrent: vi.fn(), onDraftChange },
  });
  await fireEvent.input(screen.getByLabelText('Source code'), { target: { value: 'changed' } });
  await waitFor(() =>
    expect(onDraftChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ content: 'changed', baseRevisionId: 'source-r2' }),
    ),
  );
});

it('restores a route-scoped draft and becomes clean after a successful immutable save', async () => {
  const save = vi.fn().mockResolvedValue({
    ...source,
    revisionId: 'source-r4',
    content: 'restored draft',
    href: '/source-r4',
  });
  render(VersionedSourceEditor, {
    props: {
      source,
      initialDraft: {
        objectId: source.objectId,
        baseRevisionId: source.revisionId,
        language: source.language,
        content: 'restored draft',
      },
      save,
      loadCurrent: vi.fn(),
    },
  });
  const submit = screen.getByRole('button', { name: 'Save new source version' });
  expect((screen.getByLabelText('Source code') as HTMLTextAreaElement).value).toBe(
    'restored draft',
  );
  expect((submit as HTMLButtonElement).disabled).toBe(false);
  await fireEvent.click(submit);
  await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(true));
  expect(screen.getByRole('link', { name: 'Open saved version' }).getAttribute('href')).toBe(
    '/source-r4',
  );
});
