import { expect, it } from 'vitest';
import {
  displayRelationship,
  displayRelationships,
  relationshipWrite,
} from '../../../src/web/src/lib/display-relationships';
import { objectDiagram, type WorkspaceMap } from '../../../src/web/src/lib/workspace-map';
import { proofVersion, claimVersion, structuralPin } from './version-fixtures';
import type { Relation } from '../../../src/web/src/lib/research-api';

it.each(['DEPENDS_ON', 'USES', 'PROVES', 'REFUTES'] as const)(
  'round-trips %s display and API direction',
  (kind) => {
    const write = relationshipWrite(kind, 'parent', 'child');
    const relation = { ...structuralPin('parent', 'child'), ...write } as Relation;
    expect(displayRelationship(relation)).toMatchObject({
      kind,
      parentVersionId: 'parent',
      childVersionId: 'child',
    });
  },
);

it('maps exact proof directions, premises, and duplicate declarations without mutating history', () => {
  const proof = proofVersion({
    id: 'proof-current',
    object_id: 'proof',
    content: { ...proofVersion().content, direction: 'REFUTES' },
  });
  const statement = claimVersion({ id: 'statement', object_id: 'statement' });
  const data = {
    objects: [
      { id: 'proof', kind: 'PROOF', current_object_version: proof },
      { id: 'statement', kind: 'STATEMENT', current_object_version: statement },
    ],
    nodes: [
      {
        object_id: 'proof',
        object_version_id: 'proof-old',
        title: 'Old',
        proof_direction: 'SUPPORTS',
      },
      {
        object_id: 'proof',
        object_version_id: 'proof-current',
        title: 'New',
        proof_direction: 'REFUTES',
      },
      { object_id: 'statement', object_version_id: 'statement', title: 'Statement' },
    ],
    relations: [
      structuralPin('proof-old', 'statement', 'CONCLUSION'),
      structuralPin('proof-current', 'statement', 'CONCLUSION'),
      { ...structuralPin('proof-old', 'statement'), id: 'explicit', relationship_type: 'PROVES' },
      structuralPin('proof-current', 'premise', 'PREMISE'),
      structuralPin('proof-current', 'statement'),
    ],
  } as WorkspaceMap;
  const edges = displayRelationships(data);
  expect(edges.map((edge) => edge.label)).toEqual(['Proved by', 'Refuted by', 'Depends on']);
  expect(edges[0].originals).toHaveLength(2);
  expect(edges[0].childVersionId).toBe('proof-old');
  expect(edges[1].childVersionId).toBe('proof-current');
  expect(edges[2]).toMatchObject({ parentVersionId: 'proof-current', childVersionId: 'premise' });
  const diagram = objectDiagram(data);
  expect(diagram.nodes).toHaveLength(2);
  expect(diagram.relations.map((edge) => edge.relationship_type)).toEqual(['PROVES', 'REFUTES']);
  expect(data.relations[0]).toMatchObject({
    source_object_version_id: 'proof-old',
    target_object_version_id: 'statement',
  });
});

it('does not guess the direction of an unavailable historical proof', () => {
  expect(displayRelationship(structuralPin('missing', 'statement', 'CONCLUSION'))).toBeUndefined();
  for (const kind of ['ATTACHMENT', 'TARGET', 'RESULT', 'EVIDENCE', 'ATTEMPTS', 'IMPLIES'] as const)
    expect(
      displayRelationship({ ...structuralPin('a', 'b'), relationship_type: kind } as Relation),
    ).toBeUndefined();
});
