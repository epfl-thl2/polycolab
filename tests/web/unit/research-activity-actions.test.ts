import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ResearchActivityActions from '../../../src/web/src/ui/ResearchActivityActions.svelte';

afterEach(cleanup);

it('pins independent comment and progress writes and retains failed drafts', async () => {
  const comment = vi.fn().mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce({});
  const progress = vi.fn().mockResolvedValue({});
  const onSaved = vi.fn().mockResolvedValue(undefined);
  render(ResearchActivityActions, {
    props: { targetRevisionId: 'claim-r3', comment, progress, onSaved },
  });

  const commentEditor = screen.getByLabelText('Comment');
  await fireEvent.input(commentEditor, { target: { value: 'Check the base case.' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Add comment' }));
  expect((await screen.findByRole('alert')).textContent).toContain('draft is retained');
  expect((commentEditor as HTMLTextAreaElement).value).toBe('Check the base case.');
  await fireEvent.click(screen.getByRole('button', { name: 'Add comment' }));
  await waitFor(() => expect(comment).toHaveBeenCalledTimes(2));
  expect(comment.mock.calls[1]![1]).toBe(comment.mock.calls[0]![1]);

  await fireEvent.change(screen.getByLabelText('Reported progress'), {
    target: { value: 'STALLED' },
  });
  await fireEvent.input(screen.getByLabelText('Progress detail'), {
    target: { value: 'Waiting for a sharper lemma.' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Report progress' }));
  await waitFor(() => expect(progress).toHaveBeenCalledOnce());
  expect(progress.mock.calls[0]!.slice(0, 2)).toEqual(['STALLED', 'Waiting for a sharper lemma.']);
  expect(onSaved).toHaveBeenCalledTimes(2);
});
