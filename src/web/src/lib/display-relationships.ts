import type { Relation } from './research-api';
import type { WorkspaceMap } from './workspace-map';

export const relationshipChoices = {
  DEPENDS_ON: 'Depends on',
  USES: 'Uses',
  PROVES: 'Proved by',
  REFUTES: 'Refuted by',
} as const;
export type DisplayRelationshipKind = keyof typeof relationshipChoices;
export type DisplayRelationship = {
  id: string;
  kind: DisplayRelationshipKind;
  label: string;
  parentVersionId: string;
  childVersionId: string;
  originals: Relation[];
};

export function displayRelationship(
  relation: Relation,
  proofDirection?: 'SUPPORTS' | 'REFUTES' | null,
): DisplayRelationship | undefined {
  if (relation.direction !== 'UNIDIRECTIONAL') return;
  let kind: DisplayRelationshipKind;
  let reverse = false;
  switch (relation.relationship_type) {
    case 'DEPENDS_ON':
    case 'USES':
      kind = relation.relationship_type;
      break;
    case 'PREMISE':
      kind = 'DEPENDS_ON';
      break;
    case 'PROVES':
    case 'REFUTES':
      kind = relation.relationship_type;
      reverse = true;
      break;
    case 'CONCLUSION':
      if (!proofDirection) return;
      kind = proofDirection === 'REFUTES' ? 'REFUTES' : 'PROVES';
      reverse = true;
      break;
    default:
      return;
  }
  return {
    id: relation.id,
    kind,
    label: relationshipChoices[kind],
    parentVersionId: reverse
      ? relation.target_object_version_id
      : relation.source_object_version_id,
    childVersionId: reverse ? relation.source_object_version_id : relation.target_object_version_id,
    originals: [relation],
  };
}

export function displayRelationships(data: WorkspaceMap): DisplayRelationship[] {
  const directions = new Map(
    data.nodes.map((node) => [node.object_version_id, node.proof_direction]),
  );
  for (const object of data.objects)
    if (object.current_object_version.kind === 'PROOF')
      directions.set(
        object.current_object_version.id,
        object.current_object_version.content.direction ?? 'SUPPORTS',
      );
  const result = new Map<string, DisplayRelationship>();
  for (const relation of data.relations) {
    const edge = displayRelationship(
      relation,
      relation.direction === 'UNIDIRECTIONAL'
        ? directions.get(relation.source_object_version_id)
        : undefined,
    );
    if (!edge) continue;
    const key = JSON.stringify([edge.kind, edge.parentVersionId, edge.childVersionId]);
    const existing = result.get(key);
    if (existing) existing.originals.push(relation);
    else result.set(key, edge);
  }
  return [...result.values()];
}

export function relationshipWrite(kind: DisplayRelationshipKind, parent: string, child: string) {
  const reverse = kind === 'PROVES' || kind === 'REFUTES';
  return {
    direction: 'UNIDIRECTIONAL' as const,
    relationship_type: kind,
    source_object_version_id: reverse ? child : parent,
    target_object_version_id: reverse ? parent : child,
  };
}
