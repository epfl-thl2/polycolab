import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import Commons from '../../../src/web/src/ui/Commons.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import { proofVersion } from './version-fixtures';

afterEach(() => {
  cleanup();
  history.replaceState({}, '', '/');
});

it('paginates the submitted filters, not unsubmitted input changes', async () => {
  const search = vi.fn().mockResolvedValue({ items: [], next_cursor: 'next-page' });
  render(Commons, {
    context: new Map([[contextKey, { catalogue: { search }, auth: { signedIn: false } }]]),
  });
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  await fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
  await fireEvent.input(screen.getByLabelText('Source'), { target: { value: 'Book' } });
  await fireEvent.input(screen.getByLabelText('Author'), { target: { value: 'Ada' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
  await fireEvent.input(screen.getByLabelText('Source'), { target: { value: 'Unsubmitted' } });
  await fireEvent.click(screen.getByRole('button', { name: /Load more/ }));
  await waitFor(() => expect(search).toHaveBeenCalledTimes(3));
  expect(search.mock.calls[2]![0]).toMatchObject({
    source: 'Book',
    author: 'Ada',
    cursor: 'next-page',
  });
});

it('reuses the receipt for a retry and rotates it when the admission draft changes', async () => {
  const admit = vi.fn().mockRejectedValue({ status: 503 });
  const search = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
  render(Commons, {
    context: new Map([[contextKey, { catalogue: { search, admit }, auth: { signedIn: true } }]]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Contribute' }));
  expect(document.activeElement).toBe(
    screen.getByRole('heading', { name: 'Admit a sourced statement' }),
  );
  const submit = screen.getByRole('button', { name: 'Admit publicly' }).closest('form')!;
  await fireEvent.submit(submit);
  await screen.findByRole('alert');
  await fireEvent.submit(submit);
  await waitFor(() => expect(admit).toHaveBeenCalledTimes(2));
  expect(admit.mock.calls[1]![1]).toBe(admit.mock.calls[0]![1]);
  await fireEvent.input(screen.getByLabelText('Title'), {
    target: { value: 'Changed formulation' },
  });
  await fireEvent.submit(submit);
  await waitFor(() => expect(admit).toHaveBeenCalledTimes(3));
  expect(admit.mock.calls[2]![1]).not.toBe(admit.mock.calls[1]![1]);
});

it('keeps advanced filters hidden, readable, URL-backed, and removable', async () => {
  history.replaceState({}, '', '/commons?q=compactness&kind=PROOF&author=Ada');
  const search = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
  render(Commons, {
    context: new Map([[contextKey, { catalogue: { search }, auth: { signedIn: false } }]]),
  });

  await waitFor(() =>
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'compactness', kind: 'PROOF', author: 'Ada' }),
    ),
  );
  expect(screen.getByRole('button', { name: 'Filters (2)' }).getAttribute('aria-expanded')).toBe(
    'true',
  );
  expect((screen.getByLabelText('Research type') as HTMLSelectElement).value).toBe('PROOF');
  expect(screen.getByRole('option', { name: 'Formalization' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Results for “compactness”' })).toBeTruthy();

  await fireEvent.input(screen.getByLabelText('Source'), { target: { value: 'Unsubmitted' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Remove author filter Ada' }));
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
  expect(search.mock.calls[1]![0].source).toBeUndefined();
  expect((screen.getByLabelText('Source') as HTMLInputElement).value).toBe('Unsubmitted');
  expect(location.search).toBe('?q=compactness&kind=PROOF');
  expect(screen.queryByRole('button', { name: 'Remove author filter Ada' })).toBeNull();
});

it('presents scannable results and keeps contribution out of anonymous Explore', async () => {
  const search = vi.fn().mockResolvedValue({
    items: [
      {
        catalogue_entry_id: 'entry-1',
        catalogue_status: 'Open',
        source_identifier: 'arXiv:1234.5',
        source_version: 'v2',
        source_locator: 'Theorem 4',
        object_version: proofVersion({
          id: 'revision-1',
          object_id: 'object-1',
          content: {
            ...proofVersion().content,
            title: 'A compactness argument',
            content_md: 'Use **finite satisfiability** to construct the required model.',
            reported_outcome: 'PARTIAL',
          },
        }),
      },
    ],
    next_cursor: null,
  });
  render(Commons, {
    context: new Map([[contextKey, { catalogue: { search }, auth: { signedIn: false } }]]),
  });

  const result = await screen.findByRole('article');
  expect(within(result).getByText('Proof')).toBeTruthy();
  expect(within(result).getByText('Ada')).toBeTruthy();
  expect(
    within(result).getByText('Use finite satisfiability to construct the required model.'),
  ).toBeTruthy();
  expect(within(result).getByText(/Source: arXiv:1234.5 · v2 · Theorem 4/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Contribute' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Moderator tools' })).toBeNull();
});
