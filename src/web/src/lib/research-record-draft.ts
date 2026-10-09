import type { components } from '$lib/api-client';
import type { VersionSnapshot } from './research-api';

type AttemptEvidenceRole = components['schemas']['AttemptEvidenceRole'];
type ResearchProgressStatus = components['schemas']['ResearchProgressStatus'];

/** Form state is separate from the complete wire snapshot. */
export type NewVersionDraft = {
  kind: VersionSnapshot['kind'];
  title: string;
  content_md: string;
  assumptions_md: string;
  reported_outcome: VersionSnapshot['content']['reported_outcome'];
  explanation_md?: string | null;
  change_summary: string;
};

export function newVersionSnapshot(
  draft: NewVersionDraft,
  attachmentObjectVersionIds: string[],
  proof?: ReturnType<typeof proofStructureWrite>,
  attempt?: ReturnType<typeof researchAttemptWrite>,
): VersionSnapshot {
  const content = {
    title: draft.title,
    content_md: draft.content_md,
    assumptions_md: draft.assumptions_md,
    reported_outcome: draft.reported_outcome,
    explanation_md: draft.explanation_md || null,
  };
  const common = {
    change_summary: draft.change_summary || null,
    structural_relationships: attachmentObjectVersionIds.map((id) => ({
      relationship_type: 'ATTACHMENT' as const,
      target_object_version_id: id,
    })),
  };
  if (draft.kind === 'PROOF') {
    if (!proof) throw new Error('A proof sketch requires an explicit conclusion and premise set.');
    return {
      ...common,
      kind: draft.kind,
      content: { ...content, reported_progress: proof.reported_progress, direction: 'SUPPORTS' },
      structural_relationships: [
        ...common.structural_relationships,
        { relationship_type: 'CONCLUSION', target_object_version_id: proof.conclusion_revision_id },
        ...proof.premise_revision_ids.map((id, position) => ({
          relationship_type: 'PREMISE' as const,
          target_object_version_id: id,
          position,
        })),
      ],
    };
  }
  if (draft.kind === 'ATTEMPT') {
    if (!attempt) throw new Error('An attempt requires an explicit target and findings.');
    return {
      ...common,
      kind: draft.kind,
      content: { ...content, outcome: attempt.outcome, findings_md: attempt.findings_md },
      structural_relationships: [
        ...common.structural_relationships,
        { relationship_type: 'TARGET', target_object_version_id: attempt.target_revision_id },
        ...(attempt.result_revision_id
          ? [
              {
                relationship_type: 'RESULT' as const,
                target_object_version_id: attempt.result_revision_id,
              },
            ]
          : []),
        ...(attempt.evidence ?? []).map((evidence, position) => ({
          relationship_type: 'EVIDENCE' as const,
          target_object_version_id: evidence.revision_id,
          position,
          evidence_role: evidence.role,
        })),
      ],
    };
  }
  return { ...common, kind: draft.kind, content };
}

const evidenceRoles = new Set<AttemptEvidenceRole>(['INPUT', 'SUPPORTS', 'CONTRADICTS', 'OUTPUT']);

export function proofStructureWrite(
  conclusionRevisionId: string,
  premiseRevisionIds: string[],
  reportedProgress: ResearchProgressStatus,
) {
  return {
    conclusion_revision_id: conclusionRevisionId.trim(),
    premise_revision_ids: premiseRevisionIds,
    reported_progress: reportedProgress,
  };
}

export function researchAttemptWrite(
  targetRevisionId: string,
  outcome: ResearchProgressStatus,
  findings: string,
  resultRevisionId: string,
  evidenceText: string,
) {
  const evidence = evidenceText
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf(':');
      const role = line.slice(0, separator).trim() as AttemptEvidenceRole;
      const revisionId = line.slice(separator + 1).trim();
      if (separator < 1 || !evidenceRoles.has(role) || !revisionId) {
        throw new Error(
          `Invalid evidence line “${line}”. Use ROLE: revision-id with INPUT, SUPPORTS, CONTRADICTS, or OUTPUT.`,
        );
      }
      return { role, revision_id: revisionId };
    });
  return {
    target_revision_id: targetRevisionId.trim(),
    outcome,
    findings_md: findings,
    result_revision_id: resultRevisionId.trim() || undefined,
    evidence,
  };
}
