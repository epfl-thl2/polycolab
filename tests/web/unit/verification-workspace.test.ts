import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

import VerificationWorkspace from '../../../web/src/ui/VerificationWorkspace.svelte';
import { contextKey } from '../../../web/src/svelte-lib/context';
import type { VerificationJobRead } from '../../../web/src/lib/verification-api';

afterEach(cleanup);

const snapshot: VerificationJobRead = {
  id: 'job-a',
  manifest_digest: 'a'.repeat(64),
  state: 'RUNNING',
  generation: 1,
  event_sequence: 2,
  deadline_at: '2026-09-08T01:00:00Z',
  terminal_reason: null,
  submission: {
    version: 1,
    workspace_id: 'project-a',
    work_target_object_version_id: 'target-r2',
    research_attempt_object_version_id: null,
    environment_id: 'environment-a',
    purpose: 'PYTHON_RUN',
    evidence_scope: 'Measures this exact computation only.',
    inputs: [{ path: 'main.py', role: 'SOURCE', object_version_id: 'source-r3' }],
    entrypoint: 'main.py',
    arguments: [],
    seed: 7,
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
  attempts: [],
  results: [],
};

it('inspects an exact generated job and replays only after the last committed event', async () => {
  const inspect = vi.fn().mockResolvedValue(snapshot);
  const events = vi
    .fn()
    .mockResolvedValueOnce([
      {
        sequence: 1,
        attempt_id: null,
        event_type: 'ADMITTED',
        created_at: '2026-09-08T00:00:00Z',
      },
    ])
    .mockResolvedValueOnce([
      {
        sequence: 2,
        attempt_id: 'attempt-a',
        event_type: 'CLAIMED',
        created_at: '2026-09-08T00:00:01Z',
      },
    ]);
  const objectVersionDisplays = vi.fn().mockResolvedValue({
    items: [
      { object_version_id: 'target-r2', object_id: 'target', kind: 'STATEMENT', title: 'Target' },
      { object_version_id: 'source-r3', object_id: 'source', kind: 'NOTE', title: 'Source' },
    ],
  });
  render(VerificationWorkspace, {
    props: { projectId: 'project-a', jobId: 'job-a', canWrite: true },
    context: new Map([
      [
        contextKey,
        { verification: { inspect, events }, researchStructure: { objectVersionDisplays } },
      ],
    ]),
  });

  expect(await screen.findByRole('heading', { name: 'Verification job job-a' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Source' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Refresh committed state' }));
  await waitFor(() => expect(events).toHaveBeenCalledTimes(2));
  expect(events).toHaveBeenLastCalledWith('project-a', 'job-a', 1, 100);
  expect(await screen.findByText(/#2 CLAIMED/)).toBeTruthy();
});

it('keeps exact inspection available when event replay is interrupted', async () => {
  const inspect = vi.fn().mockResolvedValue(snapshot);
  const events = vi.fn().mockRejectedValue(new Error('offline'));
  const objectVersionDisplays = vi.fn().mockResolvedValue({ items: [] });
  render(VerificationWorkspace, {
    props: { projectId: 'project-a', jobId: 'job-a', canWrite: false },
    context: new Map([
      [
        contextKey,
        { verification: { inspect, events }, researchStructure: { objectVersionDisplays } },
      ],
    ]),
  });

  expect(await screen.findByRole('heading', { name: 'Verification job job-a' })).toBeTruthy();
  expect(screen.getByRole('alert').textContent).toContain('Event connection interrupted');
  expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull();
});
