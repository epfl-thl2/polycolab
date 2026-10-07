export type ResearchObjectKind = 'STATEMENT' | 'RECORD' | 'PROOF' | 'RESEARCH_ATTEMPT';

export type ExactResearchRevisionView = {
  objectId: string;
  revisionId: string;
  kind: ResearchObjectKind;
  title: string;
  href: string;
};

export type ResearchAttemptEvidenceView = {
  id: string;
  role: string;
  revision: ExactResearchRevisionView;
};

export type ResearchAttemptView = {
  attemptId: string;
  attemptRevisionId: string;
  target: ExactResearchRevisionView;
  author: string;
  actorKind: 'HUMAN' | 'AGENT';
  createdAt: string;
  reportedProgress: 'PARTIAL' | 'COMPLETE' | 'POTENTIAL' | 'STALLED' | 'FAILED';
  outcome: string;
  findings: string;
  evidence: ResearchAttemptEvidenceView[];
  resultingRevision?: ExactResearchRevisionView;
};

export function canTargetWithResearchAttempt(target: ExactResearchRevisionView): boolean {
  return target.kind !== 'RESEARCH_ATTEMPT';
}

export type HumanNoteRevisionView = {
  revisionId: string;
  content: string;
  author: string;
  createdAt: string;
};

export type HumanNoteView = {
  ownerId: string;
  owner: string;
  canEdit: boolean;
  current: HumanNoteRevisionView;
  history: HumanNoteRevisionView[];
};

export type HumanNoteDraft = {
  objectId: string;
  baseRevisionId?: string;
  content: string;
};

export type AuthoredSummaryView = {
  revisionId: string;
  content: string;
  author: string;
  createdAt: string;
  fresh: boolean | null;
  sources: ExactResearchRevisionView[];
};

export type DerivedSummaryView = {
  content: string;
  inputDigest: string;
  fresh: boolean | null;
  rebuiltAt: string;
};

export type ResearchCommentView = {
  id: string;
  targetRevisionId: string;
  author: string;
  actorKind: 'HUMAN' | 'AGENT';
  content: string;
  createdAt: string;
};

export type ResearchProgressView = {
  id: string;
  targetRevisionId: string;
  author: string;
  actorKind: 'HUMAN' | 'AGENT';
  label: string;
  explanation: string;
  createdAt: string;
};

export type ResearchActivityTargetKind =
  ResearchObjectKind | 'HUMAN_NOTE' | 'SUMMARY' | 'COMMENT' | 'PROGRESS';

export function canAnnotateResearchRevision(kind: ResearchActivityTargetKind): boolean {
  return (
    kind === 'STATEMENT' || kind === 'RECORD' || kind === 'PROOF' || kind === 'RESEARCH_ATTEMPT'
  );
}
