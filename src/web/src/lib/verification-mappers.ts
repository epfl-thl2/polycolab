import type { components } from '$lib/api-client';

import { coarseKind } from './research-structure-mappers';
import type { ExactResearchRevisionView } from './research-structure-view';
import type { VerificationJobState, VerificationJobView } from './verification-view';

type JobRead = components['schemas']['VersionJobRead'];
type EventRead = components['schemas']['EventRead'];
type ObjectVersionDisplayRead = components['schemas']['ObjectVersionDisplayRead'];

const states: VerificationJobState[] = [
  'QUEUED',
  'RUNNING',
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'TIMED_OUT',
];

function state(value: string): VerificationJobState {
  if (states.includes(value as VerificationJobState)) return value as VerificationJobState;
  throw new Error(`Unknown verification job state: ${value}`);
}

function exactRevision(
  revisionId: string,
  projectId: string,
  displays: Map<string, ObjectVersionDisplayRead>,
): ExactResearchRevisionView {
  const display = displays.get(revisionId);
  return {
    objectId: display?.object_id ?? revisionId,
    revisionId,
    kind: display ? coarseKind(display.kind) : 'RECORD',
    title: display?.title ?? `Revision ${revisionId}`,
    href: `/workspaces/${projectId}/records/${revisionId}`,
  };
}

function resultSummary(job: JobRead) {
  const result = job.results.at(-1);
  if (!result) return job.terminal_reason ?? undefined;
  const code = result.diagnostic_summary.code;
  const exitCode = result.diagnostic_summary.exit_code;
  return [
    result.outcome,
    typeof code === 'string' && code !== 'NONE' ? code.replaceAll('_', ' ') : undefined,
    typeof exitCode === 'number' ? `exit ${exitCode}` : undefined,
  ]
    .filter(Boolean)
    .join(' · ');
}

export function mapVerificationJob(
  job: JobRead,
  events: EventRead[],
  objectVersionDisplays: ObjectVersionDisplayRead[],
): VerificationJobView {
  const displays = new Map(
    objectVersionDisplays.map((display) => [display.object_version_id, display]),
  );
  const source = job.submission.inputs.find((input) => input.role === 'SOURCE');
  if (!source?.object_version_id) throw new Error('Verification job has no exact source version.');
  const limits = job.submission.limits;
  return {
    jobId: job.id,
    generation: job.generation,
    state: state(job.state),
    purpose: job.submission.purpose,
    manifestDigest: job.manifest_digest,
    workTarget: exactRevision(
      job.submission.work_target_object_version_id,
      job.submission.workspace_id,
      displays,
    ),
    researchAttempt: job.submission.research_attempt_object_version_id
      ? exactRevision(
          job.submission.research_attempt_object_version_id,
          job.submission.workspace_id,
          displays,
        )
      : undefined,
    sourceRevisionId: source.object_version_id,
    environment: job.submission.environment_id,
    evidenceScope: job.submission.evidence_scope,
    entrypoint: job.submission.entrypoint,
    arguments: job.submission.arguments,
    inputs: job.submission.inputs.map((input) => ({
      path: input.path,
      role: input.role,
      revision: input.object_version_id
        ? exactRevision(input.object_version_id, job.submission.workspace_id, displays)
        : undefined,
      artifactId: input.artifact_id ?? undefined,
    })),
    limits: [
      { label: 'CPU count', value: String(limits.cpu_count) },
      { label: 'CPU time', value: `${limits.cpu_seconds} s` },
      { label: 'Wall time', value: `${limits.wall_seconds} s` },
      { label: 'Memory', value: `${limits.memory_bytes} bytes` },
      { label: 'Processes', value: String(limits.process_count) },
      { label: 'Writable disk', value: `${limits.disk_bytes} bytes` },
      { label: 'Output bytes', value: String(limits.output_bytes) },
      { label: 'Log bytes', value: String(limits.log_bytes) },
      { label: 'Output files', value: String(limits.output_files) },
    ],
    events: events.map((event) => ({
      id: `${job.id}:${event.sequence}`,
      sequence: event.sequence,
      eventType: event.event_type,
      attemptId: event.attempt_id ?? undefined,
      createdAt: event.created_at,
    })),
    controllerAttempts: job.attempts.map((attempt) => ({
      attemptId: attempt.id,
      generation: attempt.generation,
      outcome: attempt.state,
      startedAt: attempt.started_at,
      finishedAt: attempt.terminal_at ?? undefined,
    })),
    outputs: job.results.flatMap((result) =>
      result.outputs.map((output) => ({
        resultId: result.id,
        artifactId: output.artifact_id,
        path: output.path,
        role: output.role,
        digest: output.sha256,
        byteLength: output.byte_length,
      })),
    ),
    resultSummary: resultSummary(job),
  };
}

export function verificationRevisionIds(job: JobRead): string[] {
  return [
    job.submission.work_target_object_version_id,
    job.submission.research_attempt_object_version_id,
    ...job.submission.inputs.map((input) => input.object_version_id),
  ].filter((value): value is string => Boolean(value));
}
