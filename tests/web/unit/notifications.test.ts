import { expect, it, vi } from 'vitest';
import { Notifications } from '../../../src/web/src/svelte-lib/notifications.svelte';

it('expires visible successes while preserving paused, queued, and persistent notifications', () => {
  const notices = new Notifications();
  notices.publish({ key: 'queued', message: 'Queued success', kind: 'success' });
  notices.publish({ key: 'hovered', message: 'Hovered success', kind: 'success' });
  notices.publish({ key: 'error', message: 'Save failed', kind: 'error' });
  notices.publish({ key: 'success', message: 'Saved', kind: 'success' });
  notices.pause('hovered', true);
  notices.advance(5000, ['success', 'error', 'hovered']);
  expect(notices.items.map((item) => item.key)).toEqual(['error', 'hovered', 'queued']);
  notices.pause('hovered', false);
  notices.advance(5000, ['error', 'hovered', 'queued']);
  expect(notices.items.map((item) => item.key)).toEqual(['error']);
});

it('deduplicates a dismissed polling failure until recovery or an explicit new attempt', () => {
  const notices = new Notifications();
  const failure = { key: 'files', message: 'Storage unavailable', kind: 'error' as const };
  notices.publish(failure);
  notices.publish(failure);
  expect(notices.items).toHaveLength(1);
  notices.dismiss('files');
  notices.publish(failure);
  expect(notices.items).toHaveLength(0);
  notices.resolve('files');
  notices.publish(failure);
  expect(notices.items).toHaveLength(1);
});

it('uses the new severity lifetime when replacing an existing notification', () => {
  const notices = new Notifications();
  notices.publish({ key: 'operation', message: 'Needs attention', kind: 'info' });
  notices.publish({ key: 'operation', message: 'Needs attention', kind: 'warning' });
  notices.advance(6000, ['operation']);
  expect(notices.items[0]?.remaining).toBeNull();
  notices.publish({ key: 'operation', message: 'Needs attention', kind: 'info' });
  notices.advance(5000, ['operation']);
  expect(notices.items).toHaveLength(0);
});

it('keeps successes through project navigation and rejects late errors from the previous project', () => {
  const notices = new Notifications();
  notices.enterProject('one');
  notices.publish({ key: 'success', projectId: 'one', message: 'Deleted', kind: 'success' });
  notices.publish({ key: 'error', projectId: 'one', message: 'Failed', kind: 'error' });
  notices.enterProject('two');
  notices.publish({ key: 'late', projectId: 'one', message: 'Old project failed', kind: 'error' });
  expect(notices.items.map((item) => item.key)).toEqual(['success']);
  notices.clear();
  expect(notices.items).toHaveLength(0);
});

it('removes callbacks from disposed views while retaining safe navigation links', () => {
  const notices = new Notifications();
  const onDismiss = vi.fn();
  notices.publish({
    key: 'callback',
    message: 'Saved',
    kind: 'success',
    action: { label: 'Retry', run: vi.fn() },
    onDismiss,
  });
  notices.publish({
    key: 'link',
    message: 'Saved',
    kind: 'success',
    action: { label: 'Open', href: '/projects/one' },
  });
  notices.detach('callback');
  notices.detach('link');
  expect(notices.items.find((item) => item.key === 'callback')?.action).toBeUndefined();
  expect(notices.items.find((item) => item.key === 'link')?.action).toEqual({
    label: 'Open',
    href: '/projects/one',
  });
  notices.dismiss('callback');
  expect(onDismiss).not.toHaveBeenCalled();
});
