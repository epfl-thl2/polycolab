export type EndorsementState = 'ENDORSED' | 'WITHDRAWN' | 'DISAGREEMENT' | 'UNASSESSED';
export type CorrespondenceStatus = 'MATCHES' | 'PARTIAL' | 'MISMATCH' | 'UNASSESSED';
export type CorrespondenceSummary = CorrespondenceStatus | 'DISAGREEMENT';

export type EndorsementDraft = components['schemas']['ObjectVersionEndorsementWrite'];

export type CorrespondenceDraft = components['schemas']['ObjectVersionCorrespondenceWrite'];

export type AssuranceObservation = {
  id: string;
  label: string;
  outcome: string;
  observedAt?: string;
};

export type EndorsementHistoryView = {
  id: string;
  assessorId: string;
  active: boolean;
  rationale: string;
  author: string;
  createdAt: string;
};

export type CorrespondenceHistoryView = {
  id: string;
  assessorId: string;
  statementRevisionId: string;
  statementTitle: string;
  statementHref: string;
  status: CorrespondenceStatus;
  rationale: string;
  author: string;
  createdAt: string;
};

export type CurrentEndorsementView = EndorsementHistoryView;
export type CurrentCorrespondenceView = CorrespondenceHistoryView;

export type ProofSketchView = {
  sketchId: string;
  sketchRevisionId: string;
  recordKind: 'PROOF' | 'PROOF';
  title: string;
  href: string;
  author: string;
  conclusion: {
    revisionId: string;
    title: string;
    href: string;
  };
  premises: Array<{
    revisionId: string;
    title: string;
    href: string;
  }>;
  reportedProgress: string;
  endorsement: EndorsementState;
  correspondence: CorrespondenceSummary;
  currentEndorsements: CurrentEndorsementView[];
  currentCorrespondence: CurrentCorrespondenceView[];
  endorsementHistory: EndorsementHistoryView[];
  correspondenceHistory: CorrespondenceHistoryView[];
  unresolvedAssumptions: string[];
  machineObservations: AssuranceObservation[];
  historical: boolean;
};
import type { components } from '@polycolab/api-client';
