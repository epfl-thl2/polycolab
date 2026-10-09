import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import Activity from '../../../src/web/src/ui/Activity.svelte';
import type { ActivitySource } from '../../../src/web/src/lib/activity-view';

afterEach(cleanup);

it('separates an unavailable service from empty results and explicit examples', async () => {
  render(Activity);
  expect(screen.getByText('Recent submissions are coming soon')).toBeTruthy();
  expect(screen.queryByText('No matching activity')).toBeNull();
  expect(screen.queryByText('Testing a bound for regular graphs')).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Preview with examples' }));
  expect(await screen.findByText('Testing a bound for regular graphs')).toBeTruthy();
  expect(screen.getByRole('status').textContent?.replace(/\s+/g, ' ')).toContain(
    'not live research',
  );
  await fireEvent.change(screen.getByLabelText('Contributor'), { target: { value: 'human' } });
  await waitFor(() => expect(screen.queryByText('Testing a bound for regular graphs')).toBeNull());
  expect(screen.getByText('A missing assumption in the argument')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Active workspaces' }));
  expect(await screen.findByRole('heading', { name: 'Spectral gaps' })).toBeTruthy();
  expect(screen.queryByLabelText('Contributor')).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Exit example preview' }));
  expect(screen.getByText('Workspace activity is coming soon')).toBeTruthy();
});

it('paginates the selected filters and reports source failures without showing an empty state', async () => {
  const submissions = vi.fn().mockResolvedValue({
    items: [
      { id: 'first', title: 'First', kind: 'statement', createdAt: new Date().toISOString() },
    ],
    nextCursor: 'next',
  });
  const source: ActivitySource = { submissions, workspaces: vi.fn() };
  render(Activity, { props: { source } });
  await fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
  expect(submissions).toHaveBeenLastCalledWith(
    { window: 'week', actor: 'all', kind: 'all' },
    'next',
  );
  submissions.mockRejectedValueOnce(new Error('offline'));
  await fireEvent.change(screen.getByLabelText('Contributor'), { target: { value: 'human' } });
  expect((await screen.findByRole('alert')).textContent?.replace(/\s+/g, ' ')).toContain(
    'could not be loaded',
  );
  expect(screen.queryByText('No matching activity')).toBeNull();
  expect(submissions).toHaveBeenLastCalledWith(
    { window: 'week', actor: 'human', kind: 'all' },
    undefined,
  );
});

it('does not let a late response replace a newly selected view', async () => {
  let resolveOld!: (page: { items: []; nextCursor: string }) => void;
  const source: ActivitySource = {
    submissions: vi.fn(
      () =>
        new Promise<{ items: []; nextCursor: string }>((resolve) => {
          resolveOld = resolve;
        }),
    ),
    workspaces: vi.fn().mockResolvedValue({ items: [] }),
  };
  render(Activity, { props: { source } });
  await fireEvent.click(screen.getByRole('button', { name: 'Active workspaces' }));
  await screen.findByText('No matching activity');
  resolveOld({ items: [], nextCursor: 'stale' });
  await Promise.resolve();
  expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
});
