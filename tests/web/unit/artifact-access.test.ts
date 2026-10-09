import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import ArtifactAccess from '../../../src/web/src/ui/ArtifactAccess.svelte';
import type { ArtifactView } from '../../../src/web/src/lib/artifact-view';
import type { ExactResearchRevisionView } from '../../../src/web/src/lib/research-structure-view';

afterEach(cleanup);

const target: ExactResearchRevisionView = {
  objectId: 'proof-a',
  revisionId: 'proof-a-r2',
  kind: 'PROOF',
  title: 'Inductive route',
  href: '/projects/p/research/proof-a-r2',
};

const attempt: ExactResearchRevisionView = {
  objectId: 'attempt-a',
  revisionId: 'attempt-a-r1',
  kind: 'RESEARCH_ATTEMPT',
  title: 'Check the leaf case',
  href: '/projects/p/research/attempt-a-r1',
};

const artifact: ArtifactView = {
  artifactId: 'artifact-a',
  digest: 'sha256:123',
  byteLength: 42,
  mediaType: 'text/plain',
  state: 'COMMITTED',
  role: 'certificate',
  researchRevision: target,
  researchAttempt: attempt,
  attachments: [
    {
      attachmentId: 'attachment-a',
      role: 'EVIDENCE',
      researchRevision: target,
      sourceRevision: {
        objectId: 'source-a',
        revisionId: 'source-r1',
        kind: 'RECORD',
        title: 'Source file',
        href: '/projects/p/research/source-r1',
      },
      researchAttempt: attempt,
      createdAt: '2026-09-08T00:00:00Z',
    },
    {
      attachmentId: 'attachment-b',
      role: 'OUTPUT',
      researchRevision: target,
      createdAt: '2026-09-08T01:00:00Z',
    },
  ],
  provenance: [{ label: 'Environment', value: 'python@sha256:abc' }],
  downloadAvailable: true,
};

it('shows safe identity, provenance and exact attachments without treating the digest as access', async () => {
  const download = vi.fn().mockResolvedValue({});
  const onLoadMore = vi.fn();
  render(ArtifactAccess, {
    props: {
      artifacts: [artifact],
      targets: [],
      maxUploadBytes: 1000,
      download,
      hasMore: true,
      onLoadMore,
    },
  });

  const article = screen.getByRole('article', { name: 'Artifact artifact-a' });
  expect(within(article).getByText('sha256:123')).toBeTruthy();
  expect(within(article).getAllByText(/proof-a-r2/)).toHaveLength(2);
  expect(within(article).getByText(/attempt-a-r1/)).toBeTruthy();
  expect(within(article).getByText('python@sha256:abc')).toBeTruthy();
  expect(within(article).getByText('2')).toBeTruthy();
  expect(within(article).getByText('OUTPUT')).toBeTruthy();
  expect(
    within(article).getByRole('list', { name: 'Exact links for artifact artifact-a' }),
  ).toBeTruthy();
  expect(screen.getByText(/digest identifies bytes but does not grant/)).toBeTruthy();
  await fireEvent.click(within(article).getByRole('button', { name: 'Download artifact as data' }));
  await waitFor(() => expect(download).toHaveBeenCalledWith('artifact-a'));
  await fireEvent.click(screen.getByRole('button', { name: 'Load more artifacts' }));
  expect(onLoadMore).toHaveBeenCalledOnce();
});

it('retains a failed upload and its exact attachment for a deliberate retry', async () => {
  const upload = vi.fn().mockRejectedValue({ status: 503 });
  render(ArtifactAccess, {
    props: {
      artifacts: [],
      targets: [target],
      attempts: [attempt],
      maxUploadBytes: 1000,
      canUpload: true,
      upload,
      download: vi.fn(),
    },
  });

  const file = new File(['evidence'], 'result.txt', { type: 'text/plain', lastModified: 1 });
  const fileInput = screen.getByLabelText('File');
  await fireEvent.change(fileInput, { target: { files: [file] } });
  await fireEvent.change(screen.getByLabelText('Exact research version'), {
    target: { value: 'proof-a-r2' },
  });
  await fireEvent.change(screen.getByLabelText('High-level research attempt (optional)'), {
    target: { value: 'attempt-a-r1' },
  });
  const submit = screen.getByRole('button', { name: 'Upload and verify artifact' });
  await fireEvent.submit(submit.closest('form')!);
  expect((await screen.findByRole('alert')).textContent).toContain(
    'selection and exact attachment',
  );
  await fireEvent.submit(submit.closest('form')!);

  await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  expect(upload.mock.calls[0]![0]).toMatchObject({
    file,
    role: 'EVIDENCE',
    researchRevisionId: 'proof-a-r2',
    researchAttemptRevisionId: 'attempt-a-r1',
  });
  expect(upload.mock.calls[1]![0]).toEqual(upload.mock.calls[0]![0]);
});

it('rejects an oversized file locally while retaining it for correction', async () => {
  const upload = vi.fn();
  render(ArtifactAccess, {
    props: {
      artifacts: [],
      targets: [target],
      maxUploadBytes: 2,
      canUpload: true,
      upload,
      download: vi.fn(),
    },
  });

  const fileInput = screen.getByLabelText('File');
  await fireEvent.change(fileInput, {
    target: { files: [new File(['too large'], 'large.txt', { type: 'text/plain' })] },
  });
  await fireEvent.change(screen.getByLabelText('Exact research version'), {
    target: { value: 'proof-a-r2' },
  });
  await fireEvent.submit(
    screen.getByRole('button', { name: 'Upload and verify artifact' }).closest('form')!,
  );

  expect((await screen.findByRole('alert')).textContent).toContain('2 byte upload limit');
  expect(upload).not.toHaveBeenCalled();
  expect((fileInput as HTMLInputElement).files?.[0]?.name).toBe('large.txt');
  expect(screen.getByText(/Selected file: large.txt/)).toBeTruthy();
});

it('does not expose a download control when bytes are unavailable', () => {
  render(ArtifactAccess, {
    props: {
      artifacts: [{ ...artifact, downloadAvailable: false, state: 'UNAVAILABLE' }],
      targets: [],
      maxUploadBytes: 1000,
      download: vi.fn(),
    },
  });

  expect(screen.queryByRole('button', { name: 'Download artifact as data' })).toBeNull();
  expect(screen.getByText('Artifact bytes are unavailable or not authorized.')).toBeTruthy();
});
