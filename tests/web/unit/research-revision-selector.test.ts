import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';

import ResearchRevisionSelector from '../../../src/web/src/ui/ResearchRevisionSelector.svelte';

afterEach(cleanup);

it('selects one bounded exact version and never substitutes a newer result', async () => {
  const search = vi.fn().mockResolvedValue([
    {
      revisionId: 'revision-2',
      title: 'Compactness claim',
      kind: 'STATEMENT',
      workspaceName: 'Logic',
      revisionNumber: 2,
    },
  ]);
  render(ResearchRevisionSelector, {
    props: { label: 'Exact conclusion', search, required: true },
  });

  expect((screen.getByRole('button', { name: 'Search' }) as HTMLButtonElement).disabled).toBe(true);
  await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'compactness' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Search' }));

  expect(search).toHaveBeenCalledWith('compactness');
  const results = await screen.findByRole('list', { name: 'Exact conclusion search results' });
  await fireEvent.click(within(results).getByRole('button', { name: /Compactness claim/ }));
  expect(
    (screen.getByLabelText('Exact conclusion exact version ID') as HTMLInputElement).value,
  ).toBe('revision-2');
  expect(screen.getByRole('status').textContent).toMatch(/version 2.*revision-2/);

  await fireEvent.click(screen.getByRole('button', { name: 'Change selection' }));
  expect(
    (screen.getByLabelText('Exact conclusion exact version ID') as HTMLInputElement).value,
  ).toBe('');
});

it('shows bounded empty and retryable failure states', async () => {
  const search = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([]);
  render(ResearchRevisionSelector, { props: { label: 'Attempt target', search } });

  await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'target' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/could not be searched/);
  await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  expect(await screen.findByText('No matching accessible versions.')).toBeTruthy();
});
