import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import Library from '../../../src/web/src/ui/Library.svelte';
import LibraryImport from '../../../src/web/src/ui/LibraryImport.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import type { CatalogueEntry } from '../../../src/web/src/lib/catalogue-api';
import { claimVersion } from './version-fixtures';

const entry: CatalogueEntry = {
  entry_id: '11111111-1111-4111-8111-111111111111',
  admitted_at: '2026-09-10T00:00:00Z',
  reported_status: 'Open',
  source: { identifier: 'Book', version: '2', locator: 'Question 7' },
  object_version: claimVersion({
    object_id: '11111111-1111-4111-8111-111111111111',
    id: '22222222-2222-4222-8222-222222222222',
    number: 2,
    kind: 'PROBLEM',
    content: {
      ...claimVersion().content,
      title: 'A spectral gap question',
      content_md: 'Bound $\\lambda_2$ uniformly.',
      assumptions_md: 'Finite graphs.',
    },
  }),
};
afterEach(() => {
  cleanup();
  history.replaceState({}, '', '/');
});

it('shows statement status and literature without inventing a human review', async () => {
  const library = vi.fn().mockResolvedValue({ items: [entry], next_cursor: null });
  render(Library, {
    context: new Map([
      [contextKey, { catalogue: { library }, records: {}, auth: { signedIn: false } }],
    ]),
  });
  expect(
    await screen.findByRole('link', { name: entry.object_version.content.title }),
  ).toBeTruthy();
  expect(within(screen.getByRole('table')).getByText('Open')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Copy to workspace' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Add to Library' })).toBeNull();
});

it('reads an exact formulation with its assumptions, source, and non-verification caveat', async () => {
  const revision = vi.fn().mockResolvedValue(entry);
  render(Library, {
    props: { entryId: entry.entry_id, revisionId: entry.object_version.id },
    context: new Map([
      [
        contextKey,
        {
          catalogue: {
            revision,
            history: vi.fn().mockResolvedValue({ items: [entry], next_cursor: null }),
          },
          records: { relationPage: vi.fn().mockResolvedValue({ items: [], next_cursor: null }) },
          auth: { signedIn: false },
        },
      ],
    ]),
  });
  await screen.findByRole('heading', { name: entry.object_version.content.title });
  expect(revision).toHaveBeenCalledWith(entry.entry_id, entry.object_version.id);
  expect(screen.getByText('Finite graphs.')).toBeTruthy();
  expect(screen.getByText(/not a machine proof check/)).toBeTruthy();
  expect(screen.getByRole('link', { name: '← Library' }).getAttribute('href')).toBe('/library');
});

it('appends catalogue-only results without using general workspace discovery', async () => {
  const library = vi
    .fn()
    .mockResolvedValueOnce({ items: [entry], next_cursor: 'next' })
    .mockResolvedValueOnce({
      items: [
        {
          ...entry,
          entry_id: 'second',
          object_version: {
            ...entry.object_version,
            id: 'second-revision',
            content: { ...entry.object_version.content, title: 'Second statement' },
          },
        },
      ],
      next_cursor: null,
    });
  const search = vi.fn();
  render(Library, {
    context: new Map([
      [contextKey, { catalogue: { library, search }, records: {}, auth: { signedIn: false } }],
    ]),
  });
  await screen.findByRole('link', { name: entry.object_version.content.title });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more entries' }));
  await screen.findByRole('link', { name: 'Second statement' });
  expect(
    screen.getByRole('link', { name: entry.object_version.content.title }).getAttribute('href'),
  ).toBe(`/library/${entry.entry_id}`);
  expect(search).not.toHaveBeenCalled();
  expect(library).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'next' }));
});

it('restores URL filters and paginates submitted filters only', async () => {
  history.replaceState({}, '', '/library?q=gap&basis=review&status=Open');
  const library = vi.fn().mockResolvedValue({ items: [], next_cursor: 'next' });
  render(Library, {
    context: new Map([
      [contextKey, { catalogue: { library }, records: {}, auth: { signedIn: false } }],
    ]),
  });
  await waitFor(() =>
    expect(library).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'gap', basis: 'review', status: 'Open' }),
    ),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
  await fireEvent.input(screen.getByLabelText('Source'), { target: { value: 'Unsubmitted' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more entries' }));
  expect(library.mock.calls.at(-1)![0]).toMatchObject({
    q: 'gap',
    basis: 'review',
    cursor: 'next',
  });
  expect(library.mock.calls.at(-1)![0].source).toBeUndefined();
  await fireEvent.click(screen.getByRole('button', { name: 'Remove basis filter' }));
  expect(location.search).not.toContain('basis');
});

it('keeps failure distinct from an empty Library and recovers through retry', async () => {
  const library = vi
    .fn()
    .mockRejectedValueOnce({ status: 503 })
    .mockResolvedValue({ items: [], next_cursor: null });
  render(Library, {
    context: new Map([
      [contextKey, { catalogue: { library }, records: {}, auth: { signedIn: false } }],
    ]),
  });
  await screen.findByRole('alert');
  expect(screen.queryByText('The Library is ready for its first entry')).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await screen.findByText('The Library is ready for its first entry');
});

it('copies the displayed revision, filters destinations, and preserves retry identity', async () => {
  const copyToWorkspace = vi.fn().mockRejectedValue({ status: 503 });
  const listProjects = vi.fn().mockResolvedValue({
    items: [
      { id: 'owned', name: 'My investigation', current_user_role: 'OWNER' },
      { id: 'readonly', name: 'Read-only', current_user_role: 'READER' },
      { id: 'archive', name: 'Archived', current_user_role: 'OWNER', archived_at: '2026-09-10' },
    ],
  });
  render(LibraryImport, {
    props: { entry },
    context: new Map([
      [
        contextKey,
        {
          capabilities: { enabled: () => true },
          api: { listProjects },
          records: { copyToWorkspace },
          auth: { signedIn: true },
        },
      ],
    ]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Copy to workspace' }));
  await screen.findByRole('option', { name: 'My investigation' });
  expect(screen.queryByRole('option', { name: 'Read-only' })).toBeNull();
  expect(screen.queryByRole('option', { name: 'Archived' })).toBeNull();
  await fireEvent.change(screen.getByLabelText('Destination workspace'), {
    target: { value: 'owned' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Create copy' }));
  await screen.findByRole('alert');
  await fireEvent.click(screen.getByRole('button', { name: 'Create copy' }));
  await waitFor(() => expect(copyToWorkspace).toHaveBeenCalledTimes(2));
  expect(copyToWorkspace.mock.calls[0]![0]).toMatchObject({
    workspace_id: 'owned',
    source_object_version_id: entry.object_version.id,
  });
  expect(copyToWorkspace.mock.calls[0]![1]).toBe(copyToWorkspace.mock.calls[1]![1]);
});

it('offers admission to signed-in readers', async () => {
  render(Library, {
    context: new Map([
      [
        contextKey,
        {
          records: {},
          catalogue: { library: vi.fn().mockResolvedValue({ items: [], next_cursor: null }) },
          auth: { signedIn: true, loaded: true },
        },
      ],
    ]),
  });
  expect(screen.getByRole('link', { name: 'Add to Library' }).getAttribute('href')).toBe(
    '/library/new',
  );
});

it('requires sign in on the admission route without looking up a record named new', () => {
  const get = vi.fn();
  render(Library, {
    props: { entryId: 'new' },
    context: new Map([
      [
        contextKey,
        {
          catalogue: { get },
          auth: { signedIn: false, loaded: true },
        },
      ],
    ]),
  });
  expect(screen.getByRole('link', { name: 'Sign in' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Preview entry' })).toBeNull();
  expect(get).not.toHaveBeenCalled();
});
