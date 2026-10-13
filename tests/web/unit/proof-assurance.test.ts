import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import ProofAssurance from '../../../src/web/src/ui/ProofAssurance.svelte';
import type { ProofSketchView } from '../../../src/web/src/lib/assurance-view';

afterEach(cleanup);

const alternatives: ProofSketchView[] = [
  {
    sketchId: 'proof-a',
    sketchRevisionId: 'proof-a-r2',
    recordKind: 'PROOF',
    title: 'Inductive route',
    href: '/commons/records/proof-a-r2',
    author: 'Ada',
    conclusion: {
      revisionId: 'claim-r3',
      title: 'Every finite tree is bipartite',
      href: '/commons/records/claim-r3',
    },
    premises: [
      {
        revisionId: 'lemma-r1',
        title: 'Every finite tree has a leaf',
        href: '/commons/records/lemma-r1',
      },
      {
        revisionId: 'induction-r4',
        title: 'Induction principle',
        href: '/commons/records/induction-r4',
      },
    ],
    reportedProgress: 'Complete',
    endorsement: 'DISAGREEMENT',
    correspondence: 'UNASSESSED',
    currentEndorsements: [
      {
        id: 'endorsement-a',
        active: true,
        rationale: 'The informal argument is convincing.',
        author: 'Grace',
        createdAt: '2026-09-06',
      },
      {
        id: 'endorsement-a-withdrawn',
        active: false,
        rationale: 'A premise still needs justification.',
        author: 'Sofia',
        createdAt: '2026-09-07',
      },
    ],
    currentCorrespondence: [],
    endorsementHistory: [
      {
        id: 'endorsement-a',
        active: true,
        rationale: 'The informal argument is convincing.',
        author: 'Grace',
        createdAt: '2026-09-06',
      },
    ],
    correspondenceHistory: [],
    unresolvedAssumptions: [],
    machineObservations: [],
    historical: false,
  },
  {
    sketchId: 'proof-b',
    sketchRevisionId: 'proof-b-r1',
    recordKind: 'PROOF',
    title: 'Parity route',
    href: '/commons/records/proof-b-r1',
    author: 'Emmy',
    conclusion: {
      revisionId: 'claim-r2',
      title: 'Earlier tree formulation',
      href: '/commons/records/claim-r2',
    },
    premises: [
      {
        revisionId: 'path-r7',
        title: 'Unique path lemma',
        href: '/commons/records/path-r7',
      },
    ],
    reportedProgress: 'Partial',
    endorsement: 'UNASSESSED',
    correspondence: 'MISMATCH',
    currentEndorsements: [],
    currentCorrespondence: [
      {
        id: 'correspondence-b',
        statementRevisionId: 'claim-r2',
        statementTitle: 'Earlier tree formulation',
        statementHref: '/commons/records/claim-r2',
        status: 'MISMATCH',
        rationale: 'The formal version assumes connectedness.',
        author: 'Emmy',
        createdAt: '2026-09-07',
      },
    ],
    endorsementHistory: [
      {
        id: 'endorsement-b',
        active: false,
        rationale: 'Withdrawn after the statement changed.',
        author: 'Sofia',
        createdAt: '2026-09-07',
      },
    ],
    correspondenceHistory: [
      {
        id: 'correspondence-b',
        statementRevisionId: 'claim-r2',
        statementTitle: 'Earlier tree formulation',
        statementHref: '/commons/records/claim-r2',
        status: 'MISMATCH',
        rationale: 'The formal version assumes connectedness.',
        author: 'Emmy',
        createdAt: '2026-09-07',
      },
    ],
    unresolvedAssumptions: ['The graph is connected.'],
    machineObservations: [
      {
        id: 'lean-check-1',
        label: 'Lean compilation',
        outcome: 'Completed with unresolved axiom',
        observedAt: '2026-09-07',
      },
    ],
    historical: true,
  },
];

it('keeps alternative premise sets and assurance dimensions separate', async () => {
  const onLoadMoreCurrent = vi.fn();
  const onLoadMoreHistory = vi.fn();
  render(ProofAssurance, {
    props: {
      alternatives,
      currentStatementRevisionId: 'claim-r3',
      hasMoreCurrent: true,
      hasMoreHistory: true,
      onLoadMoreCurrent,
      onLoadMoreHistory,
    },
  });

  const articles = [
    screen.getByRole('article', { name: 'Inductive route' }),
    screen.getByRole('article', { name: 'Parity route' }),
  ];
  expect(within(articles[0]).getByText('Every finite tree has a leaf')).toBeTruthy();
  expect(within(articles[0]).queryByText('Unique path lemma')).toBeNull();
  expect(within(articles[1]).getByText('Unique path lemma')).toBeTruthy();
  expect(within(articles[1]).queryByText('Every finite tree has a leaf')).toBeNull();

  expect(within(articles[0]).getByText('Different current positions')).toBeTruthy();
  expect(within(articles[0]).getAllByText('Grace')[0]?.closest('li')?.textContent).toContain(
    'Endorsed',
  );
  expect(within(articles[0]).getByText('Sofia').closest('li')?.textContent).toContain('Withdrawn');
  expect(within(articles[0]).getByText('Not assessed')).toBeTruthy();
  expect(within(articles[1]).getByText('Mismatch')).toBeTruthy();
  expect(within(articles[1]).getByText('Conditional result')).toBeTruthy();
  expect(within(articles[1]).getByText('Historical version')).toBeTruthy();
  expect(within(articles[1]).getByText('Legacy proof record')).toBeTruthy();
  expect(within(articles[1]).getByText('Completed with unresolved axiom')).toBeTruthy();
  expect(within(articles[0]).getAllByText('The informal argument is convincing.')).toHaveLength(2);
  expect(within(articles[1]).getByText('Withdrawn')).toBeTruthy();
  expect(
    within(articles[1]).getAllByText('The formal version assumes connectedness.'),
  ).toHaveLength(2);
  expect(within(articles[1]).getByText(/later versions do not inherit them/)).toBeTruthy();

  const graphToggle = screen.getByRole('button', { name: 'Show prerequisite graph' });
  expect(graphToggle.getAttribute('aria-expanded')).toBe('false');
  await fireEvent.click(graphToggle);
  expect(
    await screen.findByText(/Proof-sketch prerequisite graph/, {}, { timeout: 10_000 }),
  ).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Hide prerequisite graph' })).toBeTruthy();
  await fireEvent.click(screen.getAllByRole('button', { name: 'Load more current positions' })[0]!);
  await fireEvent.click(screen.getAllByRole('button', { name: 'Load more assurance history' })[0]!);
  expect(onLoadMoreCurrent).toHaveBeenCalledOnce();
  expect(onLoadMoreHistory).toHaveBeenCalledOnce();
});

it('renders an explicit empty state without implying assurance', () => {
  render(ProofAssurance, {
    props: { alternatives: [], currentStatementRevisionId: 'claim-r3' },
  });

  expect(
    screen.getByText('No visible proof-sketch alternatives conclude this exact statement version.'),
  ).toBeTruthy();
  expect(
    screen.getByText(/These signals do not establish truth or catalogue admission/),
  ).toBeTruthy();
});
