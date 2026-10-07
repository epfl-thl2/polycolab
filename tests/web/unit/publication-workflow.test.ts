import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import PublicationWorkflow from '../../../web/src/ui/PublicationWorkflow.svelte';
import type {
  PublicationManifestView,
  PublicationPreviewView,
  PublicationSelectionItem,
} from '../../../web/src/lib/publication-view';

afterEach(cleanup);

const available: PublicationSelectionItem[] = [
  {
    id: 'proof-a-r2',
    kind: 'PROOF',
    revisionId: 'proof-a-r2',
    title: 'Inductive route',
    href: '/projects/p/research/proof-a-r2',
  },
  {
    id: 'summary-r1',
    kind: 'AUTHORED_SUMMARY',
    revisionId: 'summary-r1',
    title: 'Current overview',
    href: '/projects/p/research/summary-r1',
  },
];

const preview: PublicationPreviewView = {
  previewId: 'preview-1',
  digest: 'sha256:preview',
  selected: [{ ...available[0]!, inclusion: 'SELECTED' }],
  required: [
    {
      id: 'claim-r3',
      kind: 'RESEARCH_REVISION',
      revisionId: 'claim-r3',
      title: 'Tree claim',
      href: '/projects/p/research/claim-r3',
      inclusion: 'REQUIRED',
      reason: 'Exact proof-sketch conclusion',
    },
  ],
  optional: [
    {
      ...available[1]!,
      inclusion: 'OPTIONAL',
      reason: 'Authored summary',
    },
  ],
  publicFields: [{ label: 'Title', value: 'Inductive route' }],
  blockers: [],
  artifactBytesReady: true,
};

const manifest: PublicationManifestView = {
  publicationId: 'publication-1',
  digest: preview.digest,
  publishedAt: '2026-09-07',
  publisher: 'Ada',
  publicHref: '/commons/releases/publication-1',
  members: [...preview.selected, ...preview.required],
};

it('confirms only a deliberately reviewed server preview and exact digest', async () => {
  const createPreview = vi.fn().mockResolvedValue(preview);
  const confirmPublication = vi.fn().mockResolvedValue(manifest);
  render(PublicationWorkflow, {
    props: { available, actorKind: 'HUMAN', canPublish: true, createPreview, confirmPublication },
  });

  await fireEvent.click(screen.getByRole('checkbox', { name: /Inductive route/ }));
  await fireEvent.click(screen.getByRole('button', { name: 'Request exact preview' }));
  const previewSection = await screen.findByRole('region', {
    name: 'Exact sanitized public preview',
  });
  expect(within(previewSection).getByText('Tree claim')).toBeTruthy();
  expect(within(previewSection).getByText('Current overview')).toBeTruthy();
  expect(createPreview).toHaveBeenCalledWith({ selectedIds: ['proof-a-r2'] }, expect.any(String));

  const confirm = screen.getByRole('button', { name: 'Confirm exact publication' });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  await fireEvent.click(
    screen.getByRole('checkbox', { name: 'I reviewed this exact server preview and digest.' }),
  );
  await fireEvent.input(screen.getByLabelText('Publication reason'), {
    target: { value: 'Share the exact reviewed argument.' },
  });
  await fireEvent.click(confirm);
  await waitFor(() => expect(confirmPublication).toHaveBeenCalledOnce());
  expect(confirmPublication).toHaveBeenCalledWith(
    {
      previewId: 'preview-1',
      digest: 'sha256:preview',
      reason: 'Share the exact reviewed argument.',
    },
    expect.any(String),
  );
  expect(await screen.findByRole('link', { name: /Open immutable public release/ })).toBeTruthy();
});

it('retains selection but discards a stale preview before explicit reconfirmation', async () => {
  const createPreview = vi.fn().mockResolvedValue(preview);
  const confirmPublication = vi.fn().mockRejectedValue({ status: 409 });
  render(PublicationWorkflow, {
    props: { available, actorKind: 'HUMAN', canPublish: true, createPreview, confirmPublication },
  });

  const selection = screen.getByRole('checkbox', { name: /Inductive route/ });
  await fireEvent.click(selection);
  await fireEvent.click(screen.getByRole('button', { name: 'Request exact preview' }));
  await screen.findByRole('region', { name: 'Exact sanitized public preview' });
  await fireEvent.click(
    screen.getByRole('checkbox', { name: 'I reviewed this exact server preview and digest.' }),
  );
  await fireEvent.input(screen.getByLabelText('Publication reason'), {
    target: { value: 'Publish the reviewed selection.' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Confirm exact publication' }));

  expect(await screen.findByRole('alert')).toHaveProperty(
    'textContent',
    expect.stringContaining('Request and explicitly review a fresh preview.'),
  );
  expect(selection.getAttribute('aria-checked')).toBe('true');
  expect(screen.queryByRole('region', { name: 'Exact sanitized public preview' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Request exact preview' })).toBeTruthy();
});

it('blocks confirmation for server errors or unavailable artifact bytes', async () => {
  const createPreview = vi.fn().mockResolvedValue({
    ...preview,
    blockers: [{ code: 'missing_dependency', message: 'A premise is inaccessible.' }],
    artifactBytesReady: false,
  });
  render(PublicationWorkflow, {
    props: {
      available,
      actorKind: 'HUMAN',
      canPublish: true,
      createPreview,
      confirmPublication: vi.fn(),
    },
  });

  await fireEvent.click(screen.getByRole('checkbox', { name: /Inductive route/ }));
  await fireEvent.click(screen.getByRole('button', { name: 'Request exact preview' }));
  expect(await screen.findByText('A premise is inaccessible.')).toBeTruthy();
  expect(screen.getByText(/Required artifact bytes are not available/)).toBeTruthy();
  await fireEvent.click(
    screen.getByRole('checkbox', { name: 'I reviewed this exact server preview and digest.' }),
  );
  await fireEvent.input(screen.getByLabelText('Publication reason'), {
    target: { value: 'Publish exact work.' },
  });
  expect(
    (screen.getByRole('button', { name: 'Confirm exact publication' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it('does not expose selection controls to agents', () => {
  render(PublicationWorkflow, {
    props: {
      available,
      actorKind: 'AGENT',
      canPublish: true,
      createPreview: vi.fn(),
      confirmPublication: vi.fn(),
    },
  });

  expect(screen.getByText('Agents cannot publish private research.')).toBeTruthy();
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.getByText(/human notes, derived summaries/)).toBeTruthy();
});
