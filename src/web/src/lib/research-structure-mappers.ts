import type { components } from '$lib/api-client';
import type { ProofSketchView } from './assurance-view';
import type { ObjectVersion } from './research-api';
import { proofStructure, attemptStructure } from './version-snapshot';
import type {
  AuthoredSummaryView,
  ExactResearchRevisionView,
  HumanNoteView,
  ResearchAttemptView,
  ResearchCommentView,
  ResearchObjectKind,
  ResearchProgressView,
} from './research-structure-view';

type AssuranceRead = components['schemas']['ObjectVersionAssuranceRead'];
type AssuranceCurrentRead = components['schemas']['ObjectVersionCurrentAssuranceRead'];
type HumanNoteRead = components['schemas']['HumanNoteRead'];
type HumanNoteRevisionRead = components['schemas']['HumanNoteRevisionRead'];
type ResearchSummaryRead = components['schemas']['ResearchSummaryVersionRead'];
type ResearchSummaryRevisionRead = components['schemas']['ResearchSummaryVersionRevisionRead'];
type ResearchCommentRead = components['schemas']['ResearchCommentVersionRead'];
type ResearchProgressRead = components['schemas']['ResearchProgressVersionRead'];

export type RevisionDisplay = { title: string; href: string; objectId?: string };
export type RevisionDisplayResolver = (revisionId: string) => RevisionDisplay | undefined;

const actorName = (value: {
  actor_kind?: string;
  agent_display_name?: string | null;
  author_display_name?: string | null;
}) =>
  (value.actor_kind === 'AGENT' ? value.agent_display_name : value.author_display_name) ??
  'Unknown contributor';

export function coarseKind(kind: components['schemas']['ObjectKind']): ResearchObjectKind {
  if (kind === 'ATTEMPT') return 'RESEARCH_ATTEMPT';
  if (kind === 'PROOF') return 'PROOF';
  if (kind === 'PROBLEM' || kind === 'DEFINITION' || kind === 'STATEMENT') return 'STATEMENT';
  return 'RECORD';
}

export function exactRevision(record: ObjectVersion, href: string): ExactResearchRevisionView {
  return {
    objectId: record.object_id,
    revisionId: record.id,
    kind: coarseKind(record.kind),
    title: record.content.title,
    href,
  };
}

export function mapProofSketch(
  record: ObjectVersion,
  currentAssurance: AssuranceCurrentRead,
  assuranceHistory: AssuranceRead,
  resolve: RevisionDisplayResolver,
  href: string,
  currentConclusionRevisionId: string,
): ProofSketchView | undefined {
  const structure = proofStructure(record);
  if (!structure) return undefined;
  const conclusion = resolve(structure.conclusionObjectVersionId);
  const currentEndorsements = currentAssurance.endorsements;
  const currentCorrespondence = currentAssurance.correspondence.filter(
    (item) => item.statement_object_version_id === structure.conclusionObjectVersionId,
  );
  const endorsementStates = new Set(currentEndorsements.map((item) => item.active));
  const correspondenceStates = new Set(currentCorrespondence.map((item) => item.status));
  const correspondenceHistory = assuranceHistory.correspondence.filter(
    (item) => item.statement_object_version_id === structure.conclusionObjectVersionId,
  );
  const mapEndorsement = (item: AssuranceRead['endorsements'][number]) => ({
    id: item.id,
    assessorId: item.assessor_id,
    active: item.active,
    rationale: item.rationale,
    author: item.author_display_name ?? 'Unknown human',
    createdAt: item.created_at,
  });
  const mapCorrespondence = (item: AssuranceRead['correspondence'][number]) => {
    const statement = resolve(item.statement_object_version_id);
    return {
      id: item.id,
      assessorId: item.assessor_id,
      statementRevisionId: item.statement_object_version_id,
      statementTitle: statement?.title ?? `Revision ${item.statement_object_version_id}`,
      statementHref: statement?.href ?? '#',
      status: item.status,
      rationale: item.rationale,
      author: item.author_display_name ?? 'Unknown human',
      createdAt: item.created_at,
    };
  };
  return {
    sketchId: record.object_id,
    sketchRevisionId: record.id,
    recordKind: record.kind === 'PROOF' ? 'PROOF' : 'PROOF',
    title: record.content.title,
    href,
    author: actorName(record.authorship),
    conclusion: {
      revisionId: structure.conclusionObjectVersionId,
      title: conclusion?.title ?? `Revision ${structure.conclusionObjectVersionId}`,
      href: conclusion?.href ?? '#',
    },
    premises: structure.premiseObjectVersionIds.map((revisionId) => {
      const premise = resolve(revisionId);
      return {
        revisionId,
        title: premise?.title ?? `Revision ${revisionId}`,
        href: premise?.href ?? '#',
      };
    }),
    reportedProgress: structure.reportedProgress,
    endorsement:
      endorsementStates.size > 1
        ? 'DISAGREEMENT'
        : currentEndorsements[0]?.active
          ? 'ENDORSED'
          : currentEndorsements.length > 0
            ? 'WITHDRAWN'
            : 'UNASSESSED',
    correspondence:
      correspondenceStates.size > 1
        ? 'DISAGREEMENT'
        : (currentCorrespondence[0]?.status ?? 'UNASSESSED'),
    currentEndorsements: currentEndorsements.map(mapEndorsement),
    currentCorrespondence: currentCorrespondence.map(mapCorrespondence),
    endorsementHistory: assuranceHistory.endorsements.map(mapEndorsement),
    correspondenceHistory: correspondenceHistory.map(mapCorrespondence),
    unresolvedAssumptions:
      record.content.assumptions_md && record.content.assumptions_md !== 'None stated'
        ? [record.content.assumptions_md]
        : [],
    machineObservations: [],
    historical: structure.conclusionObjectVersionId !== currentConclusionRevisionId,
  };
}

export function mapResearchAttempt(
  record: ObjectVersion,
  resolve: RevisionDisplayResolver,
): ResearchAttemptView | undefined {
  const attempt = attemptStructure(record);
  if (!attempt) return undefined;
  const target = resolve(attempt.targetObjectVersionId);
  const result = attempt.resultObjectVersionId ? resolve(attempt.resultObjectVersionId) : undefined;
  return {
    attemptId: record.object_id,
    attemptRevisionId: record.id,
    target: {
      objectId: target?.objectId ?? attempt.targetObjectVersionId,
      revisionId: attempt.targetObjectVersionId,
      kind: 'RECORD',
      title: target?.title ?? `Version ${attempt.targetObjectVersionId}`,
      href: target?.href ?? '#',
    },
    author: actorName(record.authorship),
    actorKind: record.authorship.actor_kind === 'AGENT' ? 'AGENT' : 'HUMAN',
    createdAt: record.created_at,
    reportedProgress: attempt.outcome,
    outcome: record.content.title,
    findings: attempt.findings,
    evidence: attempt.evidence.map((item) => {
      const evidence = resolve(item.objectVersionId);
      return {
        id: `${record.id}:${item.role}:${item.objectVersionId}`,
        role: item.role,
        revision: {
          objectId: evidence?.objectId ?? item.objectVersionId,
          revisionId: item.objectVersionId,
          kind: 'RECORD',
          title: evidence?.title ?? `Version ${item.objectVersionId}`,
          href: evidence?.href ?? '#',
        },
      };
    }),
    resultingRevision: attempt.resultObjectVersionId
      ? {
          objectId: result?.objectId ?? attempt.resultObjectVersionId,
          revisionId: attempt.resultObjectVersionId,
          kind: 'RECORD',
          title: result?.title ?? `Version ${attempt.resultObjectVersionId}`,
          href: result?.href ?? '#',
        }
      : undefined,
  };
}

const mapNoteRevision = (revision: HumanNoteRevisionRead) => ({
  revisionId: revision.id,
  content: revision.body_md,
  author: revision.author_display_name ?? 'Unknown human',
  createdAt: revision.created_at,
});

export function mapHumanNote(note: HumanNoteRead, history: HumanNoteRevisionRead[]): HumanNoteView {
  return {
    ownerId: note.owner_user_id,
    owner: note.owner_display_name ?? 'Unknown human',
    canEdit: note.can_edit,
    current: mapNoteRevision(note.current_revision),
    history: history.map(mapNoteRevision),
  };
}

export function mapAuthoredSummary(
  summary: ResearchSummaryRead,
  resolve: RevisionDisplayResolver,
): AuthoredSummaryView {
  const revision = summary.current_revision;
  return {
    revisionId: revision.id,
    content: revision.body_md,
    author: actorName(revision),
    createdAt: revision.created_at,
    fresh: revision.fresh,
    sources: revision.source_object_version_ids.map((revisionId) => {
      const source = resolve(revisionId);
      return {
        objectId: source?.objectId ?? revisionId,
        revisionId,
        kind: 'RECORD',
        title: source?.title ?? `Revision ${revisionId}`,
        href: source?.href ?? '#',
      };
    }),
  };
}

export function mapAuthoredSummaryRevision(
  revision: ResearchSummaryRevisionRead,
  resolve: RevisionDisplayResolver,
): AuthoredSummaryView {
  return mapAuthoredSummary(
    { object_id: revision.object_id, owner_display_name: null, current_revision: revision },
    resolve,
  );
}

export const mapResearchComment = (comment: ResearchCommentRead): ResearchCommentView => ({
  id: comment.id,
  targetRevisionId: comment.object_version_id,
  author: actorName(comment),
  actorKind: comment.actor_kind === 'AGENT' ? 'AGENT' : 'HUMAN',
  content: comment.body_md,
  createdAt: comment.created_at,
});

export const mapResearchProgress = (progress: ResearchProgressRead): ResearchProgressView => ({
  id: progress.id,
  targetRevisionId: progress.object_version_id,
  author: actorName(progress),
  actorKind: progress.actor_kind === 'AGENT' ? 'AGENT' : 'HUMAN',
  label: progress.status,
  explanation: progress.detail_md,
  createdAt: progress.created_at,
});
