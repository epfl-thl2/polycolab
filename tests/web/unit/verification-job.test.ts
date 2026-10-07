import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import VerificationJob from '../../../web/src/ui/VerificationJob.svelte';
import { acceptsJobUpdate, type VerificationJobView } from '../../../web/src/lib/verification-view';

afterEach(cleanup);

const job: VerificationJobView = {
  jobId: 'job-1',
  generation: 2,
  state: 'RUNNING',
  purpose: 'LEAN_CHECK',
  manifestDigest: 'manifest-digest',
  workTarget: {
    objectId: 'proof',
    revisionId: 'proof-r2',
    kind: 'PROOF',
    title: 'Proof',
    href: '/proof-r2',
  },
  researchAttempt: {
    objectId: 'attempt',
    revisionId: 'attempt-r1',
    kind: 'RESEARCH_ATTEMPT',
    title: 'Attempt',
    href: '/attempt-r1',
  },
  sourceRevisionId: 'source-r2',
  environment: 'lean@sha256:abc',
  evidenceScope: 'Checks the exact target under the recorded assumptions.',
  entrypoint: 'Main.lean',
  arguments: [],
  inputs: [
    {
      path: 'input.txt',
      role: 'INPUT',
      revision: {
        objectId: 'input',
        revisionId: 'input-r4',
        kind: 'RECORD',
        title: 'Pinned input',
        href: '/input-r4',
      },
    },
  ],
  limits: [{ label: 'Wall time', value: '30 s' }],
  events: [{ id: 'e1', sequence: 4, eventType: 'CLAIMED', createdAt: 'now' }],
  controllerAttempts: [{ attemptId: 'controller-2', generation: 2, outcome: 'running' }],
  outputs: [],
};

it('binds lifecycle to exact inputs and separates controller attempts', async () => {
  const cancel = vi.fn().mockResolvedValue({});
  render(VerificationJob, {
    props: { job, editorSourceRevisionId: 'source-r3', canControl: true, cancel },
  });
  expect(screen.getByText(/Exact work target:/).textContent).toContain('proof-r2');
  expect(screen.getByText(/High-level research attempt:/).textContent).toContain('attempt-r1');
  expect(screen.getByRole('link', { name: 'Pinned input' }).getAttribute('href')).toBe('/input-r4');
  expect(screen.getByText(/Historical result/)).toBeTruthy();
  expect(screen.getByText(/Controller retries are operational/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
  await waitFor(() => expect(cancel).toHaveBeenCalledWith('job-1'));
  expect(await screen.findByRole('status')).toHaveProperty(
    'textContent',
    expect.stringContaining('committed terminal event'),
  );
});

it('replays after the last committed sequence and keeps rerun gated on isolation', async () => {
  const reconnect = vi.fn().mockResolvedValue({});
  const rerun = vi.fn();
  render(VerificationJob, {
    props: {
      job: { ...job, state: 'FAILED' },
      canControl: true,
      connectionInterrupted: true,
      reconnect,
      rerun,
    },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Reconnect and replay' }));
  expect(reconnect).toHaveBeenCalledWith('job-1', 4);
  expect(
    (screen.getByRole('button', { name: 'Rerun exact job' }) as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(screen.getByText(/Linux isolation gate/)).toBeTruthy();
});

it('fences updates by job identity and generation', () => {
  expect(acceptsJobUpdate(job, { ...job, generation: 3 })).toBe(true);
  expect(acceptsJobUpdate(job, { ...job, generation: 1 })).toBe(false);
  expect(acceptsJobUpdate(job, { ...job, jobId: 'job-2' })).toBe(false);
  expect(
    acceptsJobUpdate(job, {
      ...job,
      events: [{ ...job.events[0]!, sequence: 3 }],
    }),
  ).toBe(false);
  expect(
    acceptsJobUpdate(
      { ...job, state: 'CANCELLED' },
      { ...job, state: 'RUNNING', events: [{ ...job.events[0]!, sequence: 5 }] },
    ),
  ).toBe(false);
});

it.each(['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'] as const)(
  'renders the canonical %s state without implying an estimate',
  (state) => {
    render(VerificationJob, { props: { job: { ...job, state } } });
    expect(screen.getByText(state.replace('_', ' '), { selector: 'strong' })).toBeTruthy();
    if (state === 'QUEUED')
      expect(screen.getByText('Queued. No completion estimate is available.')).toBeTruthy();
  },
);
