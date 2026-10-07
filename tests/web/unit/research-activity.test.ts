import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ResearchActivity from '../../../web/src/ui/ResearchActivity.svelte';

afterEach(cleanup);

it('pins comments and append-only progress to an exact revision without implying assurance', () => {
  render(ResearchActivity, {
    props: {
      targetRevisionId: 'proof-a-r2',
      targetKind: 'PROOF',
      comments: [
        {
          id: 'comment-a',
          targetRevisionId: 'proof-a-r2',
          author: 'Ada',
          actorKind: 'HUMAN',
          content: 'The induction base is explicit.',
          createdAt: '2026-09-07',
        },
      ],
      progress: [
        {
          id: 'progress-a',
          targetRevisionId: 'proof-a-r2',
          author: 'solver',
          actorKind: 'AGENT',
          label: 'Premise checked',
          explanation: 'The leaf lemma was reviewed.',
          createdAt: '2026-09-07',
        },
      ],
    },
  });

  expect(screen.getByText(/Pinned to exact research version proof-a-r2/)).toBeTruthy();
  expect(screen.getAllByText(/target proof-a-r2/)).toHaveLength(2);
  expect(screen.getByText(/activity, not endorsement or verification/)).toBeTruthy();
});

it('offers actions and bounded pagination for eligible revisions', async () => {
  const onComment = vi.fn();
  const onProgress = vi.fn();
  const onLoadMore = vi.fn();
  render(ResearchActivity, {
    props: {
      targetRevisionId: 'claim-r3',
      targetKind: 'STATEMENT',
      comments: [],
      progress: [],
      canContribute: true,
      hasMore: true,
      onComment,
      onProgress,
      onLoadMore,
    },
  });

  await fireEvent.click(screen.getByRole('button', { name: 'Add comment' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Report progress' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Load more activity' }));
  expect(onComment).toHaveBeenCalledOnce();
  expect(onProgress).toHaveBeenCalledOnce();
  expect(onLoadMore).toHaveBeenCalledOnce();
});

it.each(['HUMAN_NOTE', 'SUMMARY', 'COMMENT', 'PROGRESS'] as const)(
  'prevents recursive annotation of %s streams',
  (targetKind) => {
    render(ResearchActivity, {
      props: {
        targetRevisionId: 'associated-r1',
        targetKind,
        comments: [],
        progress: [],
        canContribute: true,
      },
    });

    expect(screen.queryByRole('button', { name: 'Add comment' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Report progress' })).toBeNull();
    expect(screen.getByText(/cannot themselves be annotated/)).toBeTruthy();
  },
);
