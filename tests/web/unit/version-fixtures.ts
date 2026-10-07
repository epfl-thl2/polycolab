import type { components } from '@polycolab/api-client';

export const versionAuthorship: components['schemas']['VersionAuthorshipRead'] = {
  actor_kind: 'HUMAN',
  author_display_name: 'Ada',
  author_user_id: null,
  agent_display_name: null,
  agent_id: null,
  contribution_id: null,
  sponsor_user_id: null,
};

export function claimVersion(
  values: Partial<components['schemas']['OrdinaryObjectVersionRead']> = {},
): components['schemas']['OrdinaryObjectVersionRead'] {
  return {
    id: 'claim-r3',
    object_id: 'claim-object',
    number: 3,
    previous_object_version_id: 'claim-r2',
    kind: 'STATEMENT',
    schema_version: 1,
    change_summary: null,
    authorship: versionAuthorship,
    created_at: '2026-09-07T00:00:00Z',
    content: {
      title: 'Tree claim',
      content_md: 'Claim',
      assumptions_md: 'None stated',
      reported_outcome: null,
      explanation_md: null,
    },
    structural_relationships: [],
    ...values,
  };
}

export function structuralPin(
  source: string,
  target: string,
  role: 'ATTACHMENT' | 'CONCLUSION' | 'PREMISE' | 'TARGET' | 'RESULT' = 'ATTACHMENT',
  position: number | null = null,
): components['schemas']['UnidirectionalRelationshipRead'] {
  return {
    id: `${source}-${role}-${target}`,
    source_object_version_id: source,
    target_object_version_id: target,
    relationship_type: role,
    binding: 'STRUCTURAL',
    direction: 'UNIDIRECTIONAL',
    position,
    evidence_role: null,
    description: null,
    ownership_scope_id: null,
    authorship: versionAuthorship,
    created_at: '2026-09-07T00:00:00Z',
  };
}

export function proofVersion(
  values: Partial<components['schemas']['ProofObjectVersionRead']> = {},
): components['schemas']['ProofObjectVersionRead'] {
  return {
    ...claimVersion(),
    id: 'sketch-r2',
    object_id: 'sketch-object',
    number: 2,
    previous_object_version_id: 'sketch-r1',
    kind: 'PROOF',
    content: {
      ...claimVersion().content,
      title: 'Inductive route',
      content_md: 'Proof body',
      reported_progress: 'COMPLETE',
    },
    structural_relationships: [
      structuralPin('sketch-r2', 'claim-r3'),
      structuralPin('sketch-r2', 'claim-r3', 'CONCLUSION'),
    ],
    ...values,
  };
}
