import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import ResearchAttemptHistory from '../../../src/web/src/ui/ResearchAttemptHistory.svelte';
import type {
  ExactResearchRevisionView,
  ResearchAttemptView,
} from '../../../src/web/src/lib/research-structure-view';

afterEach(cleanup);

const target: ExactResearchRevisionView = {
  objectId: 'claim',
  revisionId: 'claim-r3',
  kind: 'STATEMENT',
  title: 'Every finite tree is bipartite',
  href: '/commons/records/claim-r3',
};

const attempt: ResearchAttemptView = {
  attemptId: 'attempt-a',
  attemptRevisionId: 'attempt-a-r1',
  target,
  author: 'Ada',
  actorKind: 'HUMAN',
  createdAt: '2026-09-07',
  reportedProgress: 'PARTIAL',
  outcome: 'Leaf induction advances the proof',
  findings: 'The remaining case needs a connectivity lemma.',
  evidence: [
    {
      id: 'evidence-a',
      role: 'supports',
      revision: {
        objectId: 'lemma',
        revisionId: 'lemma-r1',
        kind: 'STATEMENT',
        title: 'Every finite tree has a leaf',
        href: '/commons/records/lemma-r1',
      },
    },
  ],
  resultingRevision: { ...target, revisionId: 'claim-r4', href: '/commons/records/claim-r4' },
};

it('keeps exact target, findings, evidence and resulting revision distinct', () => {
  render(ResearchAttemptHistory, { props: { target, attempts: [attempt] } });

  const article = screen.getByRole('article', { name: attempt.outcome });
  expect(within(article).getByText(/Exact target:/).textContent).toContain('claim-r3');
  expect(within(article).getByText(attempt.findings)).toBeTruthy();
  expect(within(article).getByText('Every finite tree has a leaf')).toBeTruthy();
  expect(within(article).getByText(/version claim-r4/)).toBeTruthy();
  expect(within(article).getByText(/distinct from controller execution attempts/)).toBeTruthy();
  expect(within(article).getByText('Reported Partial')).toBeTruthy();
});

it('offers bounded pagination and creation only for non-attempt targets', async () => {
  const onCreate = vi.fn();
  const onLoadMore = vi.fn();
  render(ResearchAttemptHistory, {
    props: { target, attempts: [], canCreate: true, hasMore: true, onCreate, onLoadMore },
  });

  await fireEvent.click(screen.getByRole('button', { name: 'Record research attempt' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Load more attempts' }));
  expect(onCreate).toHaveBeenCalledOnce();
  expect(onLoadMore).toHaveBeenCalledOnce();
});

it('does not allow recursive attempts', () => {
  render(ResearchAttemptHistory, {
    props: {
      target: { ...target, kind: 'RESEARCH_ATTEMPT' },
      attempts: [],
      canCreate: true,
    },
  });

  expect(screen.queryByRole('button', { name: 'Record research attempt' })).toBeNull();
  expect(screen.getByText('Research attempts cannot target other research attempts.')).toBeTruthy();
});
