import { expect, it } from 'vitest';
import { groupRelationships } from '../../../src/web/src/lib/relationship-groups';
import type { WorkspaceMap } from '../../../src/web/src/lib/workspace-map';
import { claimVersion } from './version-fixtures';

it('groups directed links from the focused object perspective without substituting revisions', () => {
  const relationMeta = {
    authorship: claimVersion().authorship,
    binding: 'DECLARATION' as const,
    direction: 'UNIDIRECTIONAL' as const,
    ownership_scope_id: null,
    position: null,
    evidence_role: null,
    created_at: '2026-09-15T00:00:00Z',
    description: '',
  };
  const data: WorkspaceMap = {
    objects: [],
    nodes: [
      { object_id: 'a', object_version_id: 'a-old', title: 'A' },
      { object_id: 'a', object_version_id: 'a-new', title: 'A' },
    ],
    relations: [
      {
        ...relationMeta,
        id: 'out',
        relationship_type: 'DEPENDS_ON',
        source_object_version_id: 'a-old',
        target_object_version_id: 'b-exact',
      },
      {
        ...relationMeta,
        id: 'in',
        relationship_type: 'DEPENDS_ON',
        source_object_version_id: 'b-exact',
        target_object_version_id: 'a-new',
      },
      {
        ...relationMeta,
        id: 'proof',
        relationship_type: 'PROVES',
        source_object_version_id: 'proof-exact',
        target_object_version_id: 'a-old',
      },
      {
        ...relationMeta,
        id: 'unrelated',
        relationship_type: 'USES',
        source_object_version_id: 'x',
        target_object_version_id: 'y',
      },
    ],
  };
  const groups = groupRelationships(data, 'a');
  expect(groups.map((group) => group.label)).toEqual(['Depends on', 'Proved by', 'Referenced by']);
  expect(groups[0].items[0]).toMatchObject({
    otherRevisionId: 'b-exact',
    focusedRevisionId: 'a-old',
    direction: 'outgoing',
  });
  expect(groups[2].items[0]).toMatchObject({
    otherRevisionId: 'b-exact',
    focusedRevisionId: 'a-new',
    direction: 'incoming',
  });
  expect(groupRelationships(data, '')).toEqual([]);
});

it('hides equivalence from simplified relationship lists', () => {
  const data: WorkspaceMap = {
    objects: [],
    nodes: [
      { object_id: 'a', object_version_id: 'a-old', title: 'A' },
      { object_id: 'b', object_version_id: 'b-exact', title: 'B' },
    ],
    relations: [
      {
        id: 'equivalence',
        direction: 'BIDIRECTIONAL',
        binding: 'DECLARATION',
        relationship_type: 'EQUIVALENT_TO',
        first_object_version_id: 'a-old',
        second_object_version_id: 'b-exact',
        description: null,
        ownership_scope_id: null,
        authorship: claimVersion().authorship,
        created_at: '2026-09-16T00:00:00Z',
      },
    ],
  };
  expect(groupRelationships(data, 'a')).toEqual([]);
  expect(groupRelationships(data, 'b')).toEqual([]);
});
