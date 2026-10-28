import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import FeedbackToast from '../../../src/web/src/ui/FeedbackToast.svelte';
import ToastHost from '../../../src/web/src/ui/ToastHost.svelte';
import {
  Notifications,
  notificationsKey,
} from '../../../src/web/src/svelte-lib/notifications.svelte';

afterEach(cleanup);

it('dismisses feedback without changing the saved result and shows the next operation', async () => {
  const view = render(FeedbackToast, {
    props: {
      message: 'Saved.',
      action: { href: '/projects/project/records/revision', label: 'Read saved version' },
    },
  });
  const status = await screen.findByRole('status');
  expect(status.closest('[data-feedback-toast]')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Read saved version' }).getAttribute('href')).toBe(
    '/projects/project/records/revision',
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
  expect(screen.queryByRole('status')).toBeNull();
  await view.rerender({ message: '' });
  await view.rerender({ message: 'Saved.' });
  expect(screen.getByRole('status').textContent).toBe('Saved.');
});

it('announces failures and still calls an existing dismissal handler', async () => {
  const onDismiss = vi.fn();
  render(FeedbackToast, { props: { message: 'Save failed.', variant: 'error', onDismiss } });
  expect((await screen.findByRole('alert')).textContent).toBe('Save failed.');
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
  expect(onDismiss).toHaveBeenCalledOnce();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('shows the same failure again after a new explicit operation while keeping dismissed polling errors hidden', async () => {
  const view = render(FeedbackToast, { props: { message: 'Save failed.', variant: 'error' } });
  await screen.findByRole('alert');
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
  await view.rerender({ message: 'Save failed.' });
  expect(screen.queryByRole('alert')).toBeNull();
  await view.rerender({ pending: true });
  expect(screen.queryByRole('alert')).toBeNull();
  await view.rerender({ pending: false });
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Save failed.');
});

it('shares one host across publishers and retains successful messages after a view unmounts', async () => {
  const notifications = new Notifications();
  render(ToastHost, { props: { notifications } });
  const context = new Map([[notificationsKey, notifications]]);
  const first = render(FeedbackToast, { props: { message: 'Files saved.' }, context });
  render(FeedbackToast, { props: { message: 'Settings saved.' }, context });
  await screen.findByText('Files saved.');
  await screen.findByText('Settings saved.');
  expect(screen.getAllByRole('region', { name: 'Notifications' })).toHaveLength(1);
  first.unmount();
  expect(screen.getByText('Files saved.')).toBeTruthy();
});

it('limits the visible stack and lets users expand and dismiss queued errors', async () => {
  const notifications = new Notifications();
  for (let i = 0; i < 4; i++)
    notifications.publish({ key: `error-${i}`, message: `Failure ${i}`, kind: 'error' });
  render(ToastHost, { props: { notifications } });
  await screen.findByText('Failure 3');
  expect(screen.getAllByRole('alert')).toHaveLength(3);
  await fireEvent.click(screen.getByRole('button', { name: 'More notifications (1)' }));
  expect(screen.getAllByRole('alert')).toHaveLength(4);
  notifications.clear();
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Notifications' })).toBeNull());
});
