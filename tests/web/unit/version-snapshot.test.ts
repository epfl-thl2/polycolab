import { describe, expect, it } from 'vitest';
import type { ObjectVersion } from '../../../src/web/src/lib/research-api';
import { editableVersionSnapshot } from '../../../src/web/src/lib/version-snapshot';

function version(): ObjectVersion {
  return {
    id: 'version-1',
    object_id: 'object-1',
    kind: 'STATEMENT',
    number: 1,
    previous_object_version_id: null,
    schema_version: 1,
    change_summary: 'Original',
    created_at: '2026-09-15T00:00:00Z',
    authorship: {
      actor_kind: 'HUMAN',
      contribution_id: null,
      author_user_id: null,
      author_display_name: 'Author',
      agent_id: null,
      agent_display_name: null,
      sponsor_user_id: null,
    },
    content: {
      title: 'Claim',
      content_md: 'Body',
      assumptions_md: 'Assumptions',
      reported_outcome: null,
      explanation_md: null,
    },
    structural_relationships: [],
  };
}

describe('complete editable version snapshots', () => {
  it('copies all content without carrying server-owned metadata into writes', () => {
    const original = version();
    const snapshot = editableVersionSnapshot(original);
    expect(snapshot).toEqual({
      kind: 'STATEMENT',
      content: original.content,
      structural_relationships: [],
      change_summary: null,
    });
    snapshot.content.title = 'Edited';
    expect(original.content.title).toBe('Claim');
  });

  it('keeps exact pins and positions but removes relationship identity and authorship', () => {
    const original = version();
    original.structural_relationships = [
      {
        id: 'relationship-1',
        direction: 'UNIDIRECTIONAL',
        binding: 'STRUCTURAL',
        relationship_type: 'ATTACHMENT',
        source_object_version_id: original.id,
        target_object_version_id: 'pinned-version',
        position: null,
        evidence_role: null,
        ownership_scope_id: null,
        authorship: original.authorship,
        created_at: original.created_at,
        description: null,
      },
    ];
    expect(editableVersionSnapshot(original).structural_relationships).toEqual([
      {
        relationship_type: 'ATTACHMENT',
        target_object_version_id: 'pinned-version',
        position: null,
        evidence_role: null,
      },
    ]);
  });
});
