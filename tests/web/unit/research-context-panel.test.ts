import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ResearchContextPanel from '../../../src/web/src/ui/ResearchContextPanel.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { claimVersion, structuralPin } from './version-fixtures';

afterEach(cleanup);

it('loads the landed R2.1 resources for one exact project revision', async () => {
  const researchStructure = {
    objectVersionDisplays: vi.fn().mockResolvedValue({
      items: [
        {
          object_version_id: 'statement-r2',
          object_id: 'statement-object',
          kind: 'STATEMENT',
          title: 'Resolved statement title',
        },
      ],
    }),
    attempts: vi
      .fn()
      .mockResolvedValueOnce({ items: [], next_cursor: 'attempt-next' })
      .mockResolvedValue({ items: [], next_cursor: null }),
    humanNote: vi.fn().mockResolvedValue({
      object_id: 'claim-object',
      owner_user_id: 'different-user',
      owner_display_name: 'Grace',
      can_edit: false,
      current_revision: {
        id: 'note-r1',
        object_id: 'claim-object',
        number: 1,
        base_revision_id: null,
        body_md: 'Owner-only context',
        author_display_name: 'Grace',
        created_at: '2026-09-07T00:00:00Z',
      },
    }),
    humanNoteHistory: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    summary: vi.fn().mockRejectedValue({ status: 404 }),
    summaryHistory: vi.fn().mockRejectedValue({ status: 404 }),
    comments: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    progress: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    assurance: vi
      .fn()
      .mockResolvedValue({ object_version_id: 'claim-r3', endorsements: [], correspondence: [] }),
    currentAssurance: vi.fn().mockResolvedValue({
      object_version_id: 'claim-r3',
      endorsements: [],
      correspondence: [],
      next_cursor: null,
    }),
    endorse: vi.fn(),
    assessCorrespondence: vi.fn(),
  };
  render(ResearchContextPanel, {
    props: {
      projectId: 'project-a',
      canWrite: true,
      record: claimVersion({
        structural_relationships: [structuralPin('claim-r3', 'statement-r2')],
      }),
    },
    context: new Map([
      [
        contextKey,
        {
          researchStructure,
          artifacts: { attachments: vi.fn().mockResolvedValue({ items: [], next_cursor: null }) },
        },
      ],
    ]),
  });

  expect(await screen.findByRole('heading', { name: 'Research attempts' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Private human note' })).toBeTruthy();
  expect(screen.getByText('Owner-only context')).toBeTruthy();
  expect(screen.queryByLabelText('Private note')).toBeNull();
  expect(screen.getByRole('heading', { name: 'Research summaries' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Comments and progress' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Assess this exact version' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Artifacts' })).toBeTruthy();
  await waitFor(() =>
    expect(researchStructure.attempts).toHaveBeenCalledWith('claim-object', {
      project_id: 'project-a',
      target_object_version_id: 'claim-r3',
    }),
  );
  expect(researchStructure.assurance).toHaveBeenCalledWith('claim-r3', 'project-a');
  expect(researchStructure.currentAssurance).toHaveBeenCalledWith('claim-r3', 'project-a');
  expect(researchStructure.objectVersionDisplays).toHaveBeenCalledWith({
    project_id: 'project-a',
    object_version_ids: ['statement-r2'],
  });
  expect(screen.getByRole('option', { name: /Resolved statement title/ })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Load more attempts' }));
  await waitFor(() => expect(researchStructure.attempts).toHaveBeenCalledTimes(2));
  expect(researchStructure.attempts).toHaveBeenLastCalledWith('claim-object', {
    project_id: 'project-a',
    target_object_version_id: 'claim-r3',
    cursor: 'attempt-next',
  });
});
