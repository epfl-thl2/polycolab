import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import Search from '../../../src/web/src/ui/Search.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

afterEach(cleanup);

function setup(query = '') {
  const search = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
  const listPublicProjects = vi.fn().mockResolvedValue({ items: [], nextCursor: undefined });
  const view = render(Search, {
    props: { query },
    context: new Map([[contextKey, { catalogue: { search }, api: { listPublicProjects } }]]),
  });
  return { ...view, search, listPublicProjects };
}

it('does not query the backend before a search term is submitted', () => {
  const { search, listPublicProjects } = setup();
  expect(search).not.toHaveBeenCalled();
  expect(listPublicProjects).not.toHaveBeenCalled();
  expect(screen.getByRole('search').getAttribute('action')).toBe('/');
});

it('paginates submitted queries independently of unsubmitted edits', async () => {
  const view = setup();
  view.search.mockResolvedValue({ items: [], next_cursor: 'next' });
  await view.rerender({ query: 'geometry' });
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Load more research' })).toBeTruthy(),
  );
  await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'draft' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more research' }));
  expect(view.search).toHaveBeenLastCalledWith({ q: 'geometry', cursor: 'next' });
});

it('keeps project results usable when research search returns 404', async () => {
  const view = setup();
  view.search.mockRejectedValue({ status: 404 });
  view.listPublicProjects.mockResolvedValue({
    items: [{ id: 'project-1', name: 'Spectral gaps', description: 'Expansion' }],
  });
  await view.rerender({ query: 'spectral' });
  expect((await screen.findByRole('alert')).textContent).toContain('404');
  expect(screen.getByRole('link', { name: 'Spectral gaps' }).getAttribute('href')).toBe(
    '/projects/project-1',
  );
  expect(screen.queryByText('No matching research')).toBeNull();
});

it('ignores stale results when the URL query changes', async () => {
  const view = setup();
  let resolveOld!: (value: unknown) => void;
  view.listPublicProjects.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  await view.rerender({ query: 'old' });
  await waitFor(() => expect(view.listPublicProjects).toHaveBeenCalledWith('old', undefined));
  await view.rerender({ query: 'new' });
  await waitFor(() => expect(screen.getByText('No matching projects')).toBeTruthy());
  resolveOld({ items: [{ id: 'old', name: 'Obsolete result' }] });
  await Promise.resolve();
  expect(screen.queryByText('Obsolete result')).toBeNull();
});
