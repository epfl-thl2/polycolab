import type { ArtifactView } from './artifact-view';
import type { CorrespondenceStatus } from './assurance-view';
import type { ExactResearchRevisionView } from './research-structure-view';
import type { VerificationJobState } from './verification-view';

export type EvidenceAttribution = {
  actorKind: 'HUMAN' | 'AGENT';
  displayName: string;
};

export type PythonEvidenceView = {
  jobId: string;
  state: VerificationJobState;
  target: ExactResearchRevisionView;
  researchAttempt?: ExactResearchRevisionView;
  scope: 'EXAMPLES' | 'BOUNDED_SEARCH' | 'COUNTEREXAMPLE_CANDIDATE' | 'REPRODUCTION';
  environment: string;
  inputs: ExactResearchRevisionView[];
  stdout: string;
  stderr: string;
  logsTruncated: boolean;
  resources: Array<{ label: string; value: string }>;
  artifacts: ArtifactView[];
  rerunInstructions: string;
  attribution: EvidenceAttribution;
  historical: boolean;
  certificateGenerationJobId?: string;
  certificateVerificationJobId?: string;
  certificateVerificationOutcome?: string;
};

export type LeanDeclarationView = {
  declarationId: string;
  modulePath: string;
  name: string;
  compilation: 'COMPILED' | 'FAILED' | 'NOT_ELABORATED';
  proofPolicyOutcome: 'UNCONDITIONAL' | 'CONDITIONAL' | 'REJECTED' | 'UNASSESSED';
  policyVersion: string;
  unfinished: boolean;
  axioms: Array<{ name: string; policy: 'ALLOWED' | 'UNRESOLVED' | 'REJECTED' }>;
  correspondenceHistory: Array<{
    status: CorrespondenceStatus;
    author: string;
    createdAt: string;
    formalizationRevisionId: string;
    informalTargetRevisionId: string;
  }>;
  diagnostics: string[];
};

export type LeanFormalizationView = {
  jobId: string;
  resultId: string;
  formalizationRevision: Omit<ExactResearchRevisionView, 'kind'> & { kind: 'FORMALIZATION' };
  targetRevision: ExactResearchRevisionView;
  environment: string;
  state: VerificationJobState;
  declarations: LeanDeclarationView[];
  attribution: EvidenceAttribution;
  historical: boolean;
  cache: { reused: boolean; authorizationScope: string };
};
