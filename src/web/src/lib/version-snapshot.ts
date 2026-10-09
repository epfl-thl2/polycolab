import type { ObjectVersion, VersionSnapshot } from './research-api';

export function statementObjectVersionIds(version: ObjectVersion): string[] {
  return version.structural_relationships
    .filter((relationship) => relationship.relationship_type === 'ATTACHMENT')
    .map((relationship) => relationship.target_object_version_id);
}

export function attemptStructure(version: ObjectVersion) {
  if (version.kind !== 'ATTEMPT' || version.legacy_unstructured || !version.content.outcome)
    return undefined;
  const target = version.structural_relationships.find((r) => r.relationship_type === 'TARGET');
  if (!target) return undefined;
  return {
    targetObjectVersionId: target.target_object_version_id,
    resultObjectVersionId: version.structural_relationships.find(
      (r) => r.relationship_type === 'RESULT',
    )?.target_object_version_id,
    outcome: version.content.outcome,
    findings: version.content.findings_md ?? '',
    evidence: version.structural_relationships
      .filter((r) => r.relationship_type === 'EVIDENCE')
      .toSorted((a, b) => (a.position ?? 0) - (b.position ?? 0))
      .map((r) => {
        if (!r.evidence_role) throw new Error('Saved evidence is missing its role');
        return { objectVersionId: r.target_object_version_id, role: r.evidence_role };
      }),
  };
}

export function proofStructure(version: ObjectVersion) {
  if (version.kind !== 'PROOF') return undefined;
  const conclusion = version.structural_relationships.find(
    (r) => r.relationship_type === 'CONCLUSION',
  );
  if (!conclusion || !version.content.reported_progress) return undefined;
  return {
    conclusionObjectVersionId: conclusion.target_object_version_id,
    premiseObjectVersionIds: version.structural_relationships
      .filter((r) => r.relationship_type === 'PREMISE')
      .toSorted((a, b) => (a.position ?? 0) - (b.position ?? 0))
      .map((r) => r.target_object_version_id),
    reportedProgress: version.content.reported_progress,
  };
}

/** Copy the exact selected version; never substitute the object's newer head. */
export function editableVersionSnapshot(version: ObjectVersion): VersionSnapshot {
  const common = {
    change_summary: null,
    structural_relationships: version.structural_relationships.map((relationship) => ({
      relationship_type: relationship.relationship_type,
      target_object_version_id: relationship.target_object_version_id,
      position: relationship.position,
      evidence_role: relationship.evidence_role,
    })),
  };
  // A structural response cannot contain declaration types. Narrow explicitly
  // instead of casting malformed responses into a valid write command.
  const structural_relationships = common.structural_relationships.map((relationship) => {
    switch (relationship.relationship_type) {
      case 'ATTACHMENT':
      case 'CONCLUSION':
      case 'PREMISE':
      case 'TARGET':
      case 'EVIDENCE':
      case 'RESULT':
        return { ...relationship, relationship_type: relationship.relationship_type };
      default:
        throw new Error('Invalid structural relationship in saved version');
    }
  });
  const reported = version.content.reported_outcome;
  if (
    reported !== null &&
    !['UNASSESSED', 'IN_PROGRESS', 'FAILED', 'PARTIAL', 'SUCCEEDED'].includes(reported)
  ) {
    throw new Error('Unsupported historical outcome; review this version before editing');
  }
  const reported_outcome = reported as VersionSnapshot['content']['reported_outcome'];
  switch (version.kind) {
    case 'PROOF':
      if (!version.content.reported_progress)
        throw new Error('This proof requires structure before editing');
      return {
        ...common,
        structural_relationships,
        kind: version.kind,
        content: {
          ...version.content,
          reported_outcome,
          direction: version.content.direction ?? 'SUPPORTS',
        },
      };
    case 'ATTEMPT':
      if (version.legacy_unstructured)
        throw new Error('This attempt requires structure before editing');
      return {
        ...common,
        structural_relationships,
        kind: version.kind,
        content: { ...version.content, reported_outcome },
      };
    default:
      return {
        ...common,
        structural_relationships,
        kind: version.kind,
        content: { ...version.content, reported_outcome },
      };
  }
}
