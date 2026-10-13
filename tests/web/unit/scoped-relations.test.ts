import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ScopedRelations from '../../../src/web/src/ui/ScopedRelations.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

afterEach(cleanup);

it('keeps exact private endpoints and rotates retries only for changed relationship drafts', async () => {
  const relationPage = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
  const relate = vi.fn().mockRejectedValue({ status: 404 });
  render(ScopedRelations, {
    props: { revisionId: 'source', projectId: 'project', canWrite: true },
    context: new Map([[contextKey, { records: { relationPage, relate } }]]),
  });
  await waitFor(() => expect(relationPage).toHaveBeenCalledWith('source', undefined, 'project'));
  await fireEvent.click(screen.getByRole('button', { name: 'Add exact-version relationship' }));
  await fireEvent.input(screen.getByLabelText('Exact target version ID'), {
    target: { value: 'public-target' },
  });
  await fireEvent.input(screen.getByLabelText('Relationship description (optional)'), {
    target: { value: 'Uses this formulation' },
  });
  const save = screen.getByRole('button', { name: 'Save exact relationship' });
  await fireEvent.click(save);
  await screen.findByRole('alert');
  await fireEvent.click(save);
  await waitFor(() => expect(relate).toHaveBeenCalledTimes(2));
  expect(relate.mock.calls[0]![0]).toEqual({
    destination: { kind: 'project', project_id: 'project' },
    direction: 'UNIDIRECTIONAL',
    source_object_version_id: 'source',
    target_object_version_id: 'public-target',
    relationship_type: 'USES',
    description: 'Uses this formulation',
  });
  expect(relate.mock.calls[1]![1]).toBe(relate.mock.calls[0]![1]);
  await fireEvent.input(screen.getByLabelText('Exact target version ID'), {
    target: { value: 'different-exact-target' },
  });
  await fireEvent.click(save);
  await waitFor(() => expect(relate).toHaveBeenCalledTimes(3));
  expect(relate.mock.calls[2]![1]).not.toBe(relate.mock.calls[1]![1]);
});

it('reverses Proved by into the canonical proof-to-statement write', async () => {
  const relationPage = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
  const relate = vi.fn().mockResolvedValue({ outputs: [] });
  render(ScopedRelations, {
    props: { revisionId: 'first', canWrite: true },
    context: new Map([[contextKey, { records: { relationPage, relate } }]]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Add exact-version relationship' }));
  expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
    'Depends on',
    'Uses',
    'Proved by',
    'Refuted by',
  ]);
  await fireEvent.input(screen.getByLabelText('Library statement object-version ID'), {
    target: { value: 'library-statement' },
  });
  await fireEvent.change(screen.getByLabelText('Relationship type'), {
    target: { value: 'PROVES' },
  });
  await fireEvent.input(screen.getByLabelText('Exact target version ID'), {
    target: { value: 'second' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Save exact relationship' }));
  await waitFor(() => expect(relate).toHaveBeenCalledTimes(1));
  expect(relate.mock.calls[0]![0]).toEqual({
    destination: { kind: 'library', statement_object_version_id: 'library-statement' },
    direction: 'UNIDIRECTIONAL',
    source_object_version_id: 'second',
    target_object_version_id: 'first',
    relationship_type: 'PROVES',
    description: null,
  });
});

it('paginates anonymous relationships with exact endpoint links and no mutation controls', async () => {
  const relationPage = vi
    .fn()
    .mockResolvedValueOnce({
      items: [
        {
          id: 'edge',
          direction: 'UNIDIRECTIONAL',
          source_object_version_id: 'incoming',
          target_object_version_id: 'selected',
          relationship_type: 'USES',
          description: 'Reference',
        },
      ],
      next_cursor: 'next',
    })
    .mockResolvedValue({ items: [], next_cursor: null });
  render(ScopedRelations, {
    props: { revisionId: 'selected', canWrite: false },
    context: new Map([[contextKey, { records: { relationPage } }]]),
  });
  expect((await screen.findByRole('link', { name: 'incoming' })).getAttribute('href')).toBe(
    '/commons/records/incoming',
  );
  expect(screen.queryByRole('button', { name: 'Add exact-version relationship' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Load more relationships' }));
  await waitFor(() => expect(relationPage).toHaveBeenCalledWith('selected', 'next', undefined));
});
