import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import PublicResearchContext from '../../../src/web/src/ui/PublicResearchContext.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { claimVersion, proofVersion } from './version-fixtures';

afterEach(cleanup);

it('continues public attempt history anonymously and never exposes human notes', async () => {
  const publicAttempts = vi
    .fn()
    .mockResolvedValueOnce({ items: [], next_cursor: 'attempt-next' })
    .mockResolvedValue({ items: [], next_cursor: null });
  render(PublicResearchContext, {
    props: {
      record: claimVersion({ id: 'claim-r2', number: 2, previous_object_version_id: 'claim-r1' }),
    },
    context: new Map([
      [
        contextKey,
        {
          researchStructure: {
            publicAttempts,
            publicAssurance: vi.fn().mockResolvedValue({
              object_version_id: 'claim-r2',
              endorsements: [],
              correspondence: [],
            }),
            publicCurrentAssurance: vi.fn().mockResolvedValue({
              object_version_id: 'claim-r2',
              endorsements: [],
              correspondence: [],
              next_cursor: null,
            }),
          },
        },
      ],
    ]),
  });

  const more = await screen.findByRole('button', { name: /attempt/ });
  if (publicAttempts.mock.calls.length === 1) await fireEvent.click(more);
  await waitFor(() => expect(publicAttempts).toHaveBeenCalledTimes(2));
  expect(publicAttempts).toHaveBeenLastCalledWith('claim-object', 'claim-r2', {
    cursor: 'attempt-next',
  });
  expect(screen.getByText(/Private human notes are never/)).toBeTruthy();
});

it('keeps current disagreement separate while paging chronological assurance history', async () => {
  const publicAssurance = vi
    .fn()
    .mockResolvedValueOnce({
      object_version_id: 'sketch-r2',
      endorsements: [
        {
          id: 'history-a',
          object_version_id: 'sketch-r2',
          author_username: 'grace-user',
          active: true,
          rationale: 'Initial review',
          author_display_name: 'Grace',
          created_at: '2026-09-07T09:00:00Z',
        },
      ],
      correspondence: [],
      next_cursor: 'history-next',
    })
    .mockResolvedValue({
      object_version_id: 'sketch-r2',
      endorsements: [],
      correspondence: [
        {
          id: 'history-b',
          object_version_id: 'sketch-r2',
          statement_object_version_id: 'claim-r3',
          author_username: 'emmy-user',
          status: 'PARTIAL',
          rationale: 'Only one direction is formalized',
          author_display_name: 'Emmy',
          created_at: '2026-09-07T10:00:00Z',
        },
      ],
      next_cursor: null,
    });
  const publicCurrentAssurance = vi
    .fn()
    .mockResolvedValueOnce({
      object_version_id: 'sketch-r2',
      endorsements: [
        {
          id: 'current-a',
          object_version_id: 'sketch-r2',
          author_username: 'grace-user',
          active: false,
          rationale: 'I withdrew my position',
          author_display_name: 'Grace',
          created_at: '2026-09-08T09:00:00Z',
        },
        {
          id: 'current-b',
          object_version_id: 'sketch-r2',
          author_username: 'sofia-user',
          active: true,
          rationale: 'I still endorse it',
          author_display_name: 'Sofia',
          created_at: '2026-09-08T10:00:00Z',
        },
      ],
      correspondence: [],
      next_cursor: 'current-next',
    })
    .mockResolvedValue({
      object_version_id: 'sketch-r2',
      endorsements: [],
      correspondence: [],
      next_cursor: null,
    });

  render(PublicResearchContext, {
    props: {
      record: proofVersion(),
    },
    context: new Map([
      [
        contextKey,
        {
          researchStructure: {
            publicAttempts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
            publicAssurance,
            publicCurrentAssurance,
          },
        },
      ],
    ]),
  });

  expect(await screen.findByText('Different current positions')).toBeTruthy();
  expect(screen.getByText('I withdrew my position')).toBeTruthy();
  expect(screen.getByText('I still endorse it')).toBeTruthy();

  await fireEvent.click(screen.getByRole('button', { name: 'Load more assurance history' }));
  await waitFor(() =>
    expect(publicAssurance).toHaveBeenLastCalledWith('sketch-r2', 50, 'history-next'),
  );
  expect(screen.getByText('Different current positions')).toBeTruthy();
  expect(screen.getByText('Only one direction is formalized')).toBeTruthy();

  await fireEvent.click(screen.getByRole('button', { name: 'Load more current positions' }));
  await waitFor(() =>
    expect(publicCurrentAssurance).toHaveBeenLastCalledWith('sketch-r2', 50, 'current-next'),
  );
});
