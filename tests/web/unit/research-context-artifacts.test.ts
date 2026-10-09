import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import ResearchContextPanel from '../../../src/web/src/ui/ResearchContextPanel.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { claimVersion } from './version-fixtures';

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const artifact = {
  id: 'artifact-a',
  sha256: 'abc123',
  byte_length: 42,
  media_type: 'text/plain',
  state: 'COMMITTED' as const,
  expires_at: '2026-09-09T12:00:00Z',
};

it('discovers all artifact pages after reload without duplicating artifact identity', async () => {
  const attachments = vi
    .fn()
    .mockResolvedValueOnce({
      items: [
        {
          attachment_id: 'attachment-a',
          artifact,
          source_object_version_id: null,
          object_version_id: 'claim-r3',
          attempt_object_version_id: null,
          role: 'EVIDENCE',
          created_at: '2026-09-09T10:00:00Z',
        },
      ],
      next_cursor: 'attachment-next',
    })
    .mockResolvedValue({
      items: [
        {
          attachment_id: 'attachment-b',
          artifact,
          source_object_version_id: 'source-r1',
          object_version_id: 'claim-r3',
          attempt_object_version_id: 'attempt-r1',
          role: 'OUTPUT',
          created_at: '2026-09-09T11:00:00Z',
        },
      ],
      next_cursor: null,
    });
  const researchStructure = {
    objectVersionDisplays: vi.fn().mockResolvedValue({
      items: [
        {
          object_version_id: 'source-r1',
          object_id: 'source-object',
          kind: 'NOTE',
          title: 'Exact source',
        },
        {
          object_version_id: 'attempt-r1',
          object_id: 'attempt-object',
          kind: 'ATTEMPT',
          title: 'Failed attempt',
        },
      ],
    }),
    attempts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    humanNote: vi.fn().mockRejectedValue({ status: 404 }),
    humanNoteHistory: vi.fn().mockRejectedValue({ status: 404 }),
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
      canWrite: false,
      record: claimVersion(),
    },
    context: new Map([
      [
        contextKey,
        {
          researchStructure,
          artifacts: { attachments, download: vi.fn() },
          records: { relationPage: vi.fn().mockResolvedValue({ items: [], next_cursor: null }) },
          publication: {
            history: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
          },
        },
      ],
    ]),
  });

  const article = await screen.findByRole('article', { name: 'Artifact artifact-a' });
  expect(screen.getAllByRole('article', { name: 'Artifact artifact-a' })).toHaveLength(1);
  expect(within(article).getByText('1')).toBeTruthy();
  expect(attachments).toHaveBeenCalledWith('project-a', { object_version_id: 'claim-r3' });

  await fireEvent.click(screen.getByRole('button', { name: 'Load more artifacts' }));
  await waitFor(() =>
    expect(attachments).toHaveBeenLastCalledWith('project-a', {
      object_version_id: 'claim-r3',
      cursor: 'attachment-next',
    }),
  );
  await screen.findByText('OUTPUT');
  const updatedArticle = screen.getByRole('article', { name: 'Artifact artifact-a' });
  expect(screen.getAllByRole('article', { name: 'Artifact artifact-a' })).toHaveLength(1);
  expect(within(updatedArticle).getByText('2')).toBeTruthy();
  expect(within(updatedArticle).getByText('OUTPUT')).toBeTruthy();
  expect(within(updatedArticle).getByText('Failed attempt')).toBeTruthy();
});
