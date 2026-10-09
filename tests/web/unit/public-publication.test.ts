import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/svelte';
import PublicPublication from '../../../src/web/src/ui/PublicPublication.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { proofVersion } from './version-fixtures';

afterEach(cleanup);

it('retains immutable public artifact history while private artifact controls are disabled', async () => {
  const publicManifest = vi.fn().mockResolvedValue({
    id: 'manifest-a',
    preview_digest: 'digest-a',
    created_at: '2026-09-07T00:00:00Z',
    publisher_display_name: 'Ada',
    selection: {
      object_version_ids: ['proof-r2'],
      summary_revision_ids: [],
      comment_ids: [],
      progress_ids: [],
      relation_ids: [],
      artifact_ids: ['artifact-a'],
    },
    required_object_version_ids: [],
    public_fields: {
      object_versions: [
        proofVersion({
          object_id: 'proof-object',
          id: 'proof-r2',
          content: {
            ...proofVersion().content,
            title: 'Released proof',
            content_md: 'Sanitized exact proof body',
          },
        }),
      ],
      summaries: [],
      comments: [],
      progress: [],
      relationships: [],
      artifacts: [
        {
          id: 'artifact-a',
          sha256: 'abc123',
          byte_length: 42,
          media_type: 'text/plain',
          source_object_version_id: 'proof-r2',
          links: [
            { object_version_id: 'proof-r2', attempt_object_version_id: null, role: 'EVIDENCE' },
          ],
          author_display_name: 'Ada',
          actor_kind: 'HUMAN',
          agent_display_name: null,
          created_at: '2026-09-07T00:00:00Z',
          content_path: '/api/v1/artifacts/artifact-a/content',
        },
      ],
    },
  });
  render(PublicPublication, {
    props: { manifestId: 'manifest-a' },
    context: new Map([[contextKey, { publication: { publicManifest } }]]),
  });

  expect(
    await screen.findByRole('heading', { name: 'Immutable public research release' }),
  ).toBeTruthy();
  const released = screen.getByRole('region', { name: 'Released public fields' });
  expect(within(released).getByText('Sanitized exact proof body')).toBeTruthy();
  expect(
    screen.getByRole('link', { name: 'Download artifact artifact-a as data' }).getAttribute('href'),
  ).toBe('/api/v1/artifacts/artifact-a/content');
  expect(screen.getAllByText(/does not imply catalogue admission/)).toHaveLength(2);
  expect(publicManifest).toHaveBeenCalledWith('manifest-a');
});
