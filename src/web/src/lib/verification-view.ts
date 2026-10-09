import type { ExactResearchRevisionView } from './research-structure-view';

export type VerificationJobState =
  'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'TIMED_OUT';

export type VerificationJobEvent = {
  id: string;
  sequence: number;
  eventType: string;
  attemptId?: string;
  createdAt: string;
};

export type VerificationInputView = {
  path: string;
  role: 'SOURCE' | 'INPUT' | 'CERTIFICATE';
  revision?: ExactResearchRevisionView;
  artifactId?: string;
};

export type VerificationOutputView = {
  resultId: string;
  artifactId: string;
  path: string;
  role: 'OUTPUT' | 'CERTIFICATE' | 'DIAGNOSTIC';
  digest: string;
  byteLength: number;
};

export type ControllerAttemptView = {
  attemptId: string;
  generation: number;
  outcome: string;
  startedAt?: string;
  finishedAt?: string;
};

export type VerificationJobView = {
  jobId: string;
  generation: number;
  state: VerificationJobState;
  purpose: string;
  manifestDigest: string;
  workTarget: ExactResearchRevisionView;
  researchAttempt?: ExactResearchRevisionView;
  sourceRevisionId: string;
  environment: string;
  evidenceScope: string;
  entrypoint: string;
  arguments: string[];
  inputs: VerificationInputView[];
  limits: Array<{ label: string; value: string }>;
  events: VerificationJobEvent[];
  controllerAttempts: ControllerAttemptView[];
  outputs: VerificationOutputView[];
  resultSummary?: string;
  queuePosition?: number;
};

export function acceptsJobUpdate(current: VerificationJobView, incoming: VerificationJobView) {
  if (incoming.jobId !== current.jobId) return false;
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'];
  if (terminal.includes(current.state) && incoming.state !== current.state) return false;
  if (incoming.generation < current.generation) return false;
  if (incoming.generation > current.generation) return true;
  const currentSequence = current.events.at(-1)?.sequence ?? 0;
  const incomingSequence = incoming.events.at(-1)?.sequence ?? 0;
  if (incomingSequence < currentSequence) return false;
  return true;
}

export type SourceRevisionView = {
  objectId: string;
  revisionId: string;
  language: 'LEAN' | 'PYTHON';
  content: string;
  href: string;
};

export type SourceRevisionDraft = {
  objectId: string;
  baseRevisionId: string;
  language: SourceRevisionView['language'];
  content: string;
};
