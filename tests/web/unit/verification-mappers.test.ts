import { expect, it } from 'vitest';
import type { components } from '../../../src/web/src/lib/api-client';

import {
  mapVerificationJob,
  verificationRevisionIds,
} from '../../../src/web/src/lib/verification-mappers';

const job: components['schemas']['VersionJobRead'] = {
  id: 'job-a',
  manifest_digest: 'a'.repeat(64),
  state: 'COMPLETED',
  generation: 2,
  event_sequence: 4,
  deadline_at: '2026-09-08T01:00:00Z',
  terminal_reason: null,
  submission: {
    version: 1,
    workspace_id: 'project-a',
    work_target_object_version_id: 'target-r2',
    research_attempt_object_version_id: 'attempt-r1',
    environment_id: 'environment-a',
    purpose: 'LEAN_CHECK',
    evidence_scope: 'Checks the exact target under the recorded assumptions.',
    inputs: [
      { path: 'Main.lean', role: 'SOURCE', object_version_id: 'source-r3' },
      { path: 'certificate.bin', role: 'CERTIFICATE', artifact_id: 'artifact-a' },
    ],
    entrypoint: 'Main.lean',
    arguments: ['--quiet'],
    seed: null,
    limits: {
      cpu_count: 1,
      cpu_seconds: 30,
      wall_seconds: 60,
      memory_bytes: 268_435_456,
      process_count: 8,
      disk_bytes: 268_435_456,
      output_bytes: 1_048_576,
      log_bytes: 1_048_576,
      output_files: 8,
    },
  },
  attempts: [
    {
      id: 'controller-attempt-a',
      generation: 2,
      state: 'COMPLETED',
      started_at: '2026-09-08T00:00:00Z',
      terminal_at: '2026-09-08T00:00:10Z',
    },
  ],
  results: [
    {
      id: 'result-a',
      attempt_id: 'controller-attempt-a',
      outcome: 'COMPLETED',
      diagnostic_summary: { code: 'NONE', exit_code: 0 },
      created_at: '2026-09-08T00:00:10Z',
      outputs: [
        {
          artifact_id: 'artifact-output',
          path: 'result.json',
          role: 'OUTPUT',
          sha256: 'b'.repeat(64),
          byte_length: 42,
        },
      ],
    },
  ],
};

it('maps the generated job, exact identities, artifacts, limits and committed events', () => {
  const view = mapVerificationJob(
    job,
    [
      {
        sequence: 4,
        attempt_id: 'controller-attempt-a',
        event_type: 'COMPLETED',
        created_at: '2026-09-08T00:00:10Z',
      },
    ],
    [
      {
        object_version_id: 'target-r2',
        object_id: 'target',
        kind: 'STATEMENT',
        title: 'Target claim',
      },
      { object_version_id: 'attempt-r1', object_id: 'attempt', kind: 'ATTEMPT', title: 'Attempt' },
      {
        object_version_id: 'source-r3',
        object_id: 'source',
        kind: 'FORMALIZATION',
        title: 'Lean source',
      },
    ],
  );

  expect(view.workTarget.title).toBe('Target claim');
  expect(view.researchAttempt?.kind).toBe('RESEARCH_ATTEMPT');
  expect(view.sourceRevisionId).toBe('source-r3');
  expect(view.inputs[0]?.revision?.title).toBe('Lean source');
  expect(view.inputs[1]).toMatchObject({ artifactId: 'artifact-a', role: 'CERTIFICATE' });
  expect(view.events[0]).toMatchObject({ sequence: 4, eventType: 'COMPLETED' });
  expect(view.controllerAttempts[0]).toMatchObject({ generation: 2, outcome: 'COMPLETED' });
  expect(view.outputs[0]).toMatchObject({ artifactId: 'artifact-output', byteLength: 42 });
  expect(view.resultSummary).toBe('COMPLETED · exit 0');
  expect(view.manifestDigest).toBe('a'.repeat(64));
  expect(verificationRevisionIds(job)).toEqual(['target-r2', 'attempt-r1', 'source-r3']);
});

it('rejects unknown job states and a manifest without an exact source version', () => {
  expect(() => mapVerificationJob({ ...job, state: 'SURPRISE' }, [], [])).toThrow(
    'Unknown verification job state',
  );
  expect(() =>
    mapVerificationJob(
      {
        ...job,
        submission: {
          ...job.submission,
          inputs: [{ path: 'source.bin', role: 'SOURCE', artifact_id: 'artifact-a' }],
        },
      },
      [],
      [],
    ),
  ).toThrow('no exact source version');
});
