import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import People from '../../../src/web/src/ui/People.svelte';

afterEach(cleanup);

it('requires explicit examples before exposing searchable fictional profiles', async () => {
  render(People);
  expect(screen.getByText('Public profiles are coming soon')).toBeTruthy();
  expect(screen.queryByText('Ada Example')).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Preview with examples' }));
  await screen.findByRole('heading', { name: 'Ada Example' });
  expect(screen.getByText(/Fictional content/).textContent?.replace(/\s+/g, ' ')).toContain(
    'not live research or real accounts',
  );
  await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'Lean' } });
  await fireEvent.submit(screen.getByRole('search'));
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Ada Example' })).toBeNull());
  await fireEvent.click(screen.getByRole('button', { name: 'View profile for Noor Example' }));
  expect(
    (await screen.findByRole('dialog', { name: 'Noor Example' })).textContent?.replace(/\s+/g, ' '),
  ).toContain('Formal proof workshop');
  await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Exit example preview' }));
  expect(screen.queryByText('Noor Example')).toBeNull();
});

it('uses the source query and handles failures separately from no matches', async () => {
  const search = vi.fn().mockRejectedValue(new Error('offline'));
  render(People, { props: { source: { search, getProfile: vi.fn() } } });
  await screen.findByRole('alert');
  expect(screen.queryByText('No matching people')).toBeNull();
  search.mockResolvedValue({ items: [], nextCursor: 'next' });
  await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'logic' } });
  await fireEvent.submit(screen.getByRole('search'));
  await waitFor(() => expect(search).toHaveBeenLastCalledWith('logic', undefined));
  await fireEvent.click(await screen.findByRole('button', { name: 'Load more people' }));
  expect(search).toHaveBeenLastCalledWith('logic', 'next');
});
