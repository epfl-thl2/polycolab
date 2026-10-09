import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import CatalogueEdit from '../../../src/web/src/ui/CatalogueEdit.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import type { CatalogueEntry } from '../../../src/web/src/lib/catalogue-api';
import { claimVersion } from './version-fixtures';

afterEach(cleanup);
const entry: CatalogueEntry = {
  entry_id: 'entry',
  admitted_at: '2026-09-06T00:00:00Z',
  reported_status: 'OPEN',
  source: { identifier: 'Book', version: '1', locator: 'Lemma 1' },
  object_version: claimVersion({
    object_id: 'entry',
    id: 'old',
    number: 1,
    kind: 'STATEMENT',
    content: {
      ...claimVersion().content,
      title: 'Old lemma',
      content_md: 'Original formulation',
      assumptions_md: 'None',
    },
  }),
};

it('submits correction metadata separately from a complete note snapshot', async () => {
  const create = vi
    .fn()
    .mockResolvedValue({ outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: 'note-version' }] });
  render(CatalogueEdit, {
    props: { entry },
    context: new Map([[contextKey, { catalogue: {}, records: { create } }]]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Prepare a formulation change' }));
  await fireEvent.input(screen.getByLabelText('Reason'), {
    target: { value: 'Clarify the hypothesis' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Submit public suggestion' }));
  const link = await screen.findByRole('link', { name: 'Read the exact saved version' });
  expect(link.getAttribute('href')).toBe('/commons/records/note-version');
  const body = create.mock.calls[0]![0];
  expect(body.destination).toEqual({ kind: 'library', statement_object_version_id: 'old' });
  expect(body.snapshot).toMatchObject({
    kind: 'NOTE',
    content: {
      title: 'Suggested correction: Old lemma',
      content_md: 'Clarify the hypothesis',
      explanation_md: null,
    },
    structural_relationships: [
      { relationship_type: 'ATTACHMENT', target_object_version_id: 'old' },
    ],
  });
  expect(body.catalogue_suggestion.expected_current_object_version_id).toBe('old');
  expect(body.catalogue_suggestion).not.toHaveProperty('base_revision_id');
  expect(body.snapshot.content).not.toHaveProperty('suggestion');
});

it('retains an official-edit draft after conflict and requires explicit base selection', async () => {
  const revise = vi
    .fn()
    .mockRejectedValueOnce({ status: 409 })
    .mockResolvedValue({ object_version_id: 'saved' });
  const get = vi.fn().mockResolvedValue({
    ...entry,
    object_version: {
      ...entry.object_version,
      id: 'new',
      content: { ...entry.object_version.content, content_md: 'Concurrent formulation' },
    },
  });
  render(CatalogueEdit, {
    props: { entry },
    context: new Map([[contextKey, { catalogue: { revise, get }, records: {} }]]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Prepare a formulation change' }));
  await fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'EDIT' } });
  await fireEvent.input(screen.getByLabelText('Formulation'), {
    target: { value: 'My retained draft' },
  });
  await fireEvent.input(screen.getByLabelText('Reason'), { target: { value: 'Clarify' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Save official version' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Draft retained'));
  expect((screen.getByLabelText('Formulation') as HTMLTextAreaElement).value).toBe(
    'My retained draft',
  );
  await fireEvent.click(
    screen.getByRole('button', { name: 'Reload saved formulation for comparison' }),
  );
  await screen.findByText('Concurrent formulation');
  expect(revise).toHaveBeenCalledTimes(1);
  expect(revise.mock.calls[0]![1].expected_current_object_version_id).toBe('old');
  await fireEvent.click(
    screen.getByRole('button', { name: 'Use this exact base, retaining my edited formulation' }),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Save official version' }));
  await screen.findByRole('link', { name: 'Read the exact saved version' });
  expect(revise.mock.calls[1]![1]).toMatchObject({
    expected_current_object_version_id: 'new',
    content_md: 'My retained draft',
  });
  expect(revise.mock.calls[1]![2]).not.toBe(revise.mock.calls[0]![2]);
});
