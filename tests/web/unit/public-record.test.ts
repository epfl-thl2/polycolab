import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import PublicRecord from '../../../src/web/src/ui/PublicRecord.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { claimVersion, structuralPin } from './version-fixtures';

afterEach(cleanup);

it('reads historical source metadata and pages research pinned to that exact statement', async () => {
  const get = vi.fn().mockResolvedValue(
    claimVersion({
      object_id: 'entry',
      id: 'old-statement',
      kind: 'STATEMENT',
      number: 1,
      previous_object_version_id: null,
      content: {
        ...claimVersion().content,
        title: 'Historical formulation',
        content_md: 'Original statement',
        assumptions_md: 'Finite graph',
      },
      catalogue: {
        entry_id: 'entry',
        source: { identifier: 'Source book', version: 'v1', locator: 'Claim 1' },
        reported_status: 'OPEN',
        suggestion: null,
      },
    }),
  );
  const list = vi
    .fn()
    .mockResolvedValueOnce({
      items: [
        {
          ...claimVersion(),
          object_id: 'attempt',
          id: 'attempt-v1',
          kind: 'ATTEMPT',
          legacy_unstructured: false,
          content: {
            ...claimVersion().content,
            title: 'Earlier failed attempt',
            reported_outcome: 'FAILED',
            explanation_md: 'The premise was insufficient',
            outcome: 'FAILED',
            findings_md: 'The premise was insufficient',
          },
          structural_relationships: [structuralPin('attempt-v1', 'old-statement', 'TARGET')],
        },
      ],
      next_cursor: 'next-page',
    })
    .mockResolvedValue({ items: [], next_cursor: null });
  render(PublicRecord, {
    props: { revisionId: 'old-statement' },
    context: new Map([
      [
        contextKey,
        {
          records: {
            get,
            list,
            relationPage: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
          },
          researchStructure: {
            publicAttempts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
            publicAssurance: vi.fn().mockResolvedValue({
              revision_id: 'old-statement',
              endorsements: [],
              correspondence: [],
            }),
            publicCurrentAssurance: vi.fn().mockResolvedValue({
              revision_id: 'old-statement',
              endorsements: [],
              correspondence: [],
              next_cursor: null,
            }),
          },
          auth: { signedIn: false },
        },
      ],
    ]),
  });
  await screen.findByRole('heading', { name: 'Historical formulation' });
  await screen.findByText('Source book · v1 · Claim 1');
  expect(
    (await screen.findByRole('link', { name: 'Earlier failed attempt' })).getAttribute('href'),
  ).toBe('/commons/records/attempt-v1');
  expect(
    screen.getByRole('link', { name: 'Read current official statement' }).getAttribute('href'),
  ).toBe('/commons/entry');
  await fireEvent.click(screen.getByRole('button', { name: 'Load more attached research' }));
  await waitFor(() =>
    expect(list).toHaveBeenLastCalledWith({ statement_id: 'old-statement', cursor: 'next-page' }),
  );
  expect(screen.queryByRole('button', { name: 'Edit from this exact version' })).toBeNull();
});
