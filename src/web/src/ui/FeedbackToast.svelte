<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import ToastHost from './ToastHost.svelte';
  import {
    Notifications,
    notificationService,
    notificationProject,
    type NotificationAction,
    type NotificationKind,
  } from '../svelte-lib/notifications.svelte';
  let {
    message,
    variant = 'success',
    action,
    onDismiss,
    dedupeKey,
    pending = false,
  }: {
    message: string;
    variant?: NotificationKind;
    action?: NotificationAction;
    onDismiss?: () => void;
    dedupeKey?: string;
    pending?: boolean;
  } = $props();
  const shared = notificationService();
  const notifications = shared ?? new Notifications();
  const project = notificationProject();
  const defaultKey = crypto.randomUUID();
  let key: string = defaultKey;
  let previousProject: string | undefined;
  let previous = '';
  let previousKind: NotificationKind = 'success';
  $effect(() => {
    const value = message;
    const kind = variant;
    const waiting = pending;
    const projectId = project?.();
    const nextKey = dedupeKey ?? defaultKey;
    untrack(() => {
      if (key !== nextKey || projectId !== previousProject) {
        notifications.resolve(key);
        key = nextKey;
        previous = '';
        previousProject = projectId;
      }
      if (waiting) {
        notifications.resolve(key);
        previous = '';
        return;
      }
      if (!value) {
        if (previousKind === 'error' || previousKind === 'warning') notifications.resolve(key);
        previous = '';
        return;
      }
      if (value === previous && kind === previousKind) return;
      notifications.resolve(key);
      previous = value;
      previousKind = kind;
      notifications.publish({ key, message: value, kind, projectId, action, onDismiss });
    });
  });
  onDestroy(() => {
    if (!shared) notifications.clear();
    else if (previousKind === 'warning' || previousKind === 'error') notifications.resolve(key);
    else notifications.detach(key);
  });
</script>

{#if !shared}<ToastHost {notifications} />{/if}
