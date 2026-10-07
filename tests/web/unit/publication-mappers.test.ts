import { expect, it } from 'vitest';
import type { components } from '@polycolab/api-client';
import {
  mapPublicationManifest,
  mapPublicationPreview,
  publicationSelection,
} from '../../../web/src/lib/publication-mappers';
import { claimVersion, proofVersion, versionAuthorship } from './version-fixtures';

const record = proofVersion({
  object_id: 'proof-object',
  id: 'proof-r2',
  content: { ...proofVersion().content, title: 'Exact proof' },
});
const fields: components['schemas']['PublicationVersionFields'] = {
  object_versions: [
    record,
    claimVersion({
      object_id: 'claim',
      id: 'claim-r3',
      content: { ...claimVersion().content, title: 'Required claim' },
    }),
  ],
  summaries: [],
  comments: [],
  progress: [],
  relationships: [],
  artifacts: [],
};

it('splits local exact choices into the landed typed selection', () => {
  expect(
    publicationSelection(
      'project-a',
      [
        { id: 'proof-r2', kind: 'PROOF', title: 'Proof', href: '/proof' },
        { id: 'summary-r1', kind: 'AUTHORED_SUMMARY', title: 'Summary', href: '/summary' },
        { id: 'comment-a', kind: 'COMMENT', title: 'Comment', href: '/comment' },
        { id: 'artifact-a', kind: 'ARTIFACT', title: 'Artifact', href: '/artifact' },
      ],
      ['proof-r2', 'comment-a', 'artifact-a'],
    ),
  ).toEqual({
    workspace_id: 'project-a',
    object_version_ids: ['proof-r2'],
    summary_revision_ids: [],
    comment_ids: ['comment-a'],
    progress_ids: [],
    review_ids: [],
    relation_ids: [],
    artifact_ids: ['artifact-a'],
  });
});

it('maps only server-returned sanitized fields and required closure', () => {
  const preview = mapPublicationPreview({
    preview_digest: 'digest-a',
    selection: { workspace_id: 'project-a', object_version_ids: ['proof-r2'] },
    required_object_version_ids: ['claim-r3'],
    public_fields: fields,
  });
  expect(preview.selected.map((item) => item.id)).toEqual(['proof-r2']);
  expect(preview.required.map((item) => item.id)).toEqual(['claim-r3']);
  expect(preview.publicFields).toContainEqual({
    label: 'Record · Exact proof',
    value: 'Proof body',
  });

  const manifest = mapPublicationManifest({
    id: 'manifest-a',
    workspace_id: 'project-a',
    preview_digest: 'digest-a',
    created_at: '2026-09-07T00:00:00Z',
    publisher_display_name: 'Ada',
    selection: { workspace_id: 'project-a', object_version_ids: ['proof-r2'] },
    required_object_version_ids: ['claim-r3'],
    public_fields: fields,
  });
  expect(manifest.publicHref).toBe('/commons/publications/manifest-a');
  expect(manifest.members.find((item) => item.id === 'claim-r3')?.href).toBe(
    '/commons/records/claim-r3',
  );
});

it('renders equivalence from equal endpoints without requiring a source', () => {
  const preview = mapPublicationPreview({
    preview_digest: 'digest-equivalence',
    selection: { workspace_id: 'project-a', object_version_ids: ['proof-r2'] },
    required_object_version_ids: ['claim-r3'],
    public_fields: {
      ...fields,
      relationships: [
        {
          id: 'equivalence-a',
          direction: 'BIDIRECTIONAL',
          binding: 'DECLARATION',
          relationship_type: 'EQUIVALENT_TO',
          first_object_version_id: 'claim-r3',
          second_object_version_id: 'proof-r2',
          ownership_scope_id: null,
          authorship: versionAuthorship,
          created_at: record.created_at,
          description: 'Equivalent formulations',
        },
      ],
    },
  });
  expect(preview.selected.find((item) => item.id === 'equivalence-a')).toMatchObject({
    title: 'EQUIVALENT_TO relationship',
    href: '/workspaces/project-a/records/claim-r3',
  });
  expect(preview.publicFields).toContainEqual({
    label: 'Relation · EQUIVALENT_TO',
    value: 'Equivalent formulations',
  });
});
