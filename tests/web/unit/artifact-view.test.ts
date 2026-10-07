import { expect, it } from 'vitest';
import { mapArtifactAttachments } from '../../../web/src/lib/artifact-view';

const artifact = {
  id: 'artifact-a',
  sha256: 'abc123',
  byte_length: 42,
  media_type: 'text/plain',
  state: 'COMMITTED' as const,
  expires_at: '2026-09-09T12:00:00Z',
};

it('deduplicates artifact identities while retaining every exact attachment link', () => {
  const views = mapArtifactAttachments(
    [
      {
        attachment_id: 'attachment-a',
        artifact,
        source_object_version_id: 'source-r1',
        object_version_id: 'claim-r2',
        attempt_object_version_id: null,
        role: 'EVIDENCE',
        created_at: '2026-09-09T10:00:00Z',
      },
      {
        attachment_id: 'attachment-b',
        artifact,
        source_object_version_id: null,
        object_version_id: 'claim-r2',
        attempt_object_version_id: 'attempt-r1',
        role: 'OUTPUT',
        created_at: '2026-09-09T11:00:00Z',
      },
      {
        attachment_id: 'attachment-a',
        artifact,
        source_object_version_id: 'source-r1',
        object_version_id: 'claim-r2',
        attempt_object_version_id: null,
        role: 'EVIDENCE',
        created_at: '2026-09-09T10:00:00Z',
      },
    ],
    (revisionId) => ({
      objectId: `${revisionId}-object`,
      revisionId,
      kind: revisionId.startsWith('attempt') ? 'RESEARCH_ATTEMPT' : 'STATEMENT',
      title: revisionId,
      href: `/records/${revisionId}`,
    }),
  );

  expect(views).toHaveLength(1);
  expect(views[0]).toMatchObject({
    artifactId: 'artifact-a',
    digest: 'sha256:abc123',
    downloadAvailable: true,
  });
  expect(views[0]?.attachments.map((item) => item.attachmentId)).toEqual([
    'attachment-a',
    'attachment-b',
  ]);
  expect(views[0]?.attachments[0]).toMatchObject({
    role: 'EVIDENCE',
    sourceRevision: { revisionId: 'source-r1' },
    researchRevision: { revisionId: 'claim-r2' },
  });
  expect(views[0]?.attachments[1]).toMatchObject({
    role: 'OUTPUT',
    researchAttempt: { revisionId: 'attempt-r1' },
  });
});
