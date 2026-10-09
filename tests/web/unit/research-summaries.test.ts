import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import ResearchSummaries from '../../../src/web/src/ui/ResearchSummaries.svelte';

afterEach(cleanup);

it('distinguishes authored sources and freshness from disposable derived output', () => {
  render(ResearchSummaries, {
    props: {
      authored: {
        revisionId: 'summary-r2',
        content: 'The two approaches share a finite-tree premise.',
        author: 'Ada',
        createdAt: '2026-09-07',
        fresh: false,
        sources: [
          {
            objectId: 'proof-a',
            revisionId: 'proof-a-r2',
            kind: 'PROOF',
            title: 'Inductive route',
            href: '/commons/records/proof-a-r2',
          },
        ],
      },
      derived: {
        content: 'Index-generated overview',
        inputDigest: 'sha256:123',
        fresh: true,
        rebuiltAt: '2026-09-07',
      },
    },
  });

  const authored = screen.getByRole('article', { name: 'Authored summary' });
  expect(within(authored).getByText('Sources changed')).toBeTruthy();
  expect(within(authored).getByText('Inductive route')).toBeTruthy();
  expect(within(authored).getByText(/not assurance/)).toBeTruthy();

  const derived = screen.getByRole('article', { name: 'Derived summary' });
  expect(within(derived).getByText('Index current')).toBeTruthy();
  expect(within(derived).getByText(/Rebuildable index output/)).toBeTruthy();
  expect(within(derived).getByText(/does not substitute/)).toBeTruthy();
});

it('writes an authored summary against its exact base and ordered source revisions', async () => {
  const save = vi.fn().mockResolvedValue({
    revisionId: 'summary-r3',
    content: 'Revised synthesis',
    author: 'Ada',
    createdAt: '2026-09-07',
    fresh: null,
    sources: [],
  });
  render(ResearchSummaries, {
    props: {
      canEdit: true,
      save,
      authored: {
        revisionId: 'summary-r2',
        content: 'Old synthesis',
        author: 'Ada',
        createdAt: '2026-09-07',
        fresh: null,
        sources: [{ objectId: 'a', revisionId: 'a-r2', kind: 'RECORD', title: 'A', href: '/a' }],
      },
    },
  });

  await fireEvent.input(screen.getByLabelText('Summary'), {
    target: { value: 'Revised synthesis' },
  });
  await fireEvent.input(screen.getByLabelText(/Exact source version IDs/), {
    target: { value: 'b-r1\na-r2' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Save authored summary' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]!.slice(0, 3)).toEqual([
    'Revised synthesis',
    ['b-r1', 'a-r2'],
    'summary-r2',
  ]);
  expect(await screen.findByText('Authored summary saved with exact sources.')).toBeTruthy();
});
