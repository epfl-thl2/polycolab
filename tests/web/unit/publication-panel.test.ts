import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import PublicationPanel from '../../../src/web/src/ui/PublicationPanel.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { proofVersion } from './version-fixtures';

vi.mock('../../../src/web/src/lib/reviews-api', () => ({
  listReviews: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
}));
afterEach(cleanup);

const record = proofVersion({
  object_id: 'proof-object',
  id: 'proof-r2',
  content: { ...proofVersion().content, title: 'Exact proof' },
});

it('confirms the unchanged server preview selection and refreshes immutable history', async () => {
  const preview = vi.fn().mockResolvedValue({
    preview_digest: 'digest-a',
    selection: {
      project_id: 'project-a',
      object_version_ids: ['proof-r2'],
      artifact_ids: ['artifact-a'],
    },
    required_object_version_ids: [],
    public_fields: {
      object_versions: [record],
      summaries: [],
      comments: [],
      progress: [],
      relationships: [],
      artifacts: [],
    },
  });
  const confirm = vi.fn().mockResolvedValue({
    id: 'manifest-a',
    project_id: 'project-a',
    preview_digest: 'digest-a',
    created_at: '2026-09-07T00:00:00Z',
    publisher_display_name: 'Ada',
    selection: { project_id: 'project-a', object_version_ids: ['proof-r2'] },
    required_object_version_ids: [],
    public_fields: {
      object_versions: [record],
      summaries: [],
      comments: [],
      progress: [],
      relationships: [],
      artifacts: [],
    },
  });
  render(PublicationPanel, {
    props: {
      projectId: 'project-a',
      record: proofVersion({
        id: 'proof-r2',
        object_id: 'proof-object',
        previous_object_version_id: 'proof-r1',
        content: { ...proofVersion().content, title: 'Exact proof' },
      }),
      comments: [],
      progress: [],
      artifacts: [
        {
          artifactId: 'artifact-a',
          digest: 'sha256:abc123',
          byteLength: 42,
          mediaType: 'text/plain',
          state: 'COMMITTED',
          role: 'EVIDENCE',
          researchRevision: {
            objectId: 'proof-object',
            revisionId: 'proof-r2',
            kind: 'PROOF',
            title: 'Exact proof',
            href: '/projects/project-a/records/proof-r2',
          },
          provenance: [],
          downloadAvailable: true,
        },
      ],
      canPublish: true,
    },
    context: new Map([
      [
        contextKey,
        {
          records: {
            relationPage: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
          },
          publication: {
            preview,
            confirm,
            history: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
          },
        },
      ],
    ]),
  });

  await fireEvent.click(await screen.findByRole('checkbox', { name: /Exact proof/ }));
  await fireEvent.click(screen.getByRole('checkbox', { name: /Artifact artifact-a/ }));
  await fireEvent.click(screen.getByRole('button', { name: 'Request exact preview' }));
  await screen.findByRole('region', { name: 'Exact sanitized public preview' });
  await fireEvent.click(screen.getByRole('checkbox', { name: /I reviewed this exact server/ }));
  await fireEvent.input(screen.getByLabelText('Publication reason'), {
    target: { value: 'Release the reviewed proof.' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Confirm exact publication' }));

  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(preview).toHaveBeenCalledWith({
    project_id: 'project-a',
    object_version_ids: ['proof-r2'],
    summary_revision_ids: [],
    comment_ids: [],
    progress_ids: [],
    review_ids: [],
    relation_ids: [],
    artifact_ids: ['artifact-a'],
  });
  expect(confirm).toHaveBeenCalledWith(
    {
      project_id: 'project-a',
      object_version_ids: ['proof-r2'],
      artifact_ids: ['artifact-a'],
      preview_digest: 'digest-a',
      reason: 'Release the reviewed proof.',
    },
    expect.any(String),
  );
  expect(await screen.findByRole('link', { name: 'Release manifest-a' })).toBeTruthy();
});
