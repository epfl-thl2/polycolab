import { getContext } from 'svelte';
import { SvelteSet } from 'svelte/reactivity';

export type NotificationKind = 'success' | 'info' | 'warning' | 'error';
export type NotificationAction =
  { label: string; href: string } | { label: string; run: () => unknown | Promise<unknown> };
export type NotificationInput = {
  key: string;
  message: string;
  kind: NotificationKind;
  projectId?: string;
  action?: NotificationAction;
  onDismiss?: () => void;
};
export type Notification = NotificationInput & { remaining: number | null };

export class Notifications {
  items = $state<Notification[]>([]);
  private dismissed = new SvelteSet<string>();
  private paused = new SvelteSet<string>();
  private project: string | null | undefined;

  publish(input: NotificationInput) {
    if (!input.message || this.dismissed.has(input.key)) return;
    const persistent = input.kind === 'error' || input.kind === 'warning';
    if (
      persistent &&
      input.projectId &&
      this.project !== undefined &&
      input.projectId !== this.project
    )
      return;
    const previous = this.items.find((item) => item.key === input.key);
    const remaining = persistent ? null : 5000;
    this.items = [
      {
        ...input,
        remaining:
          previous?.message === input.message && previous.kind === input.kind
            ? previous.remaining
            : remaining,
      },
      ...this.items.filter((item) => item.key !== input.key),
    ];
  }

  dismiss(key: string) {
    const item = this.items.find((entry) => entry.key === key);
    this.dismissed.add(key);
    this.items = this.items.filter((entry) => entry.key !== key);
    this.paused.delete(key);
    item?.onDismiss?.();
  }

  resolve(key: string) {
    this.items = this.items.filter((item) => item.key !== key);
    this.dismissed.delete(key);
    this.paused.delete(key);
  }

  detach(key: string) {
    this.items = this.items.map((item) =>
      item.key === key
        ? {
            ...item,
            onDismiss: undefined,
            action: item.action && 'href' in item.action ? item.action : undefined,
          }
        : item,
    );
  }

  pause(key: string, paused: boolean) {
    if (paused) this.paused.add(key);
    else this.paused.delete(key);
  }

  advance(milliseconds: number, visible: string[]) {
    const shown = new SvelteSet(visible);
    this.items = this.items
      .map((item) =>
        item.remaining !== null && shown.has(item.key) && !this.paused.has(item.key)
          ? { ...item, remaining: item.remaining - milliseconds }
          : item,
      )
      .filter((item) => item.remaining === null || item.remaining > 0);
  }

  enterProject(project: string | null) {
    if (project === this.project) return;
    this.project = project;
    this.items = this.items.filter(
      (item) => !item.projectId || item.remaining !== null || item.projectId === project,
    );
    this.dismissed.clear();
  }

  clear() {
    this.items = [];
    this.dismissed.clear();
    this.paused.clear();
  }
}

export const notificationsKey = Symbol('notifications');
export const notificationProjectKey = Symbol('notification-project');
export const notificationService = () => getContext<Notifications | undefined>(notificationsKey);
export const notificationProject = () =>
  getContext<(() => string) | undefined>(notificationProjectKey);
