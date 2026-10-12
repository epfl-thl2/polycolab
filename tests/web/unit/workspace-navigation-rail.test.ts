import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { Auth } from '../../../src/web/src/svelte-lib/auth.svelte';
import WorkspaceNavigationRail from '../../../src/web/src/ui/WorkspaceNavigationRail.svelte';
afterEach(cleanup);
function setup(extra = {}) {
  const onNavigate = vi.fn();
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: true, username: 'ada', display_name: 'Ada Lovelace' };
  auth.loaded = true;
  const result = render(WorkspaceNavigationRail, {
    auth,
    projectId: 'workspace',
    section: 'research',
    canManage: true,
    onNavigate,
    ...extra,
  });
  return { ...result, onNavigate, auth };
}
it('uses explicit overview and workspace paths with the selected section', async () => {
  const { onNavigate } = setup();
  expect(screen.getByRole('link', { name: 'Research objects' }).getAttribute('aria-current')).toBe(
    'page',
  );
  await fireEvent.click(screen.getByRole('link', { name: 'Project' }));
  expect(onNavigate).toHaveBeenCalledWith('/workspaces/workspace/overview');
  await fireEvent.click(screen.getByRole('link', { name: /^Workspace$/ }));
  expect(onNavigate).toHaveBeenCalledWith('/workspaces/workspace/sessions');
  expect(
    screen.getByRole('complementary', { name: 'Workspace navigation' }).classList.contains('open'),
  ).toBe(false);
  expect(screen.getByRole('button', { name: 'Open account menu' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Agents' })).toBeNull();
});
it('keeps the icon rail fixed on hover and keyboard focus with no pin control', async () => {
  const { container } = setup();
  const rail = screen.getByRole('complementary', { name: 'Workspace navigation' });
  await fireEvent.mouseEnter(rail);
  await fireEvent.focusIn(screen.getByRole('link', { name: 'Project' }));
  expect(rail.classList.contains('open')).toBe(false);
  expect(container.querySelector('.rail-slot')?.classList.contains('reserved')).toBe(false);
  expect(screen.queryByRole('button', { name: /Pin workspace navigation/ })).toBeNull();
  expect(screen.getByRole('link', { name: 'Project' }).getAttribute('title')).toBeNull();
});
it('shows the mobile drawer expanded and limits workspace management links', () => {
  setup({ expanded: true, canManage: false });
  const rail = screen.getByRole('complementary', { name: 'Workspace navigation' });
  expect(rail.classList.contains('open')).toBe(true);
  expect(screen.queryByRole('button', { name: 'Pin workspace navigation' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Workspace settings' })).toBeNull();
  expect(screen.getByRole('link', { name: 'Agent connect' })).toBeTruthy();
});
it('preserves modified clicks for opening navigation in another tab', async () => {
  const { onNavigate } = setup();
  await fireEvent.click(screen.getByRole('link', { name: 'Map' }), { ctrlKey: true });
  expect(onNavigate).not.toHaveBeenCalled();
});

it('opens the shared account menu without leaving the workspace and supports sign out', async () => {
  const { onNavigate, auth } = setup();
  const signOut = vi.spyOn(auth, 'signOut').mockResolvedValue(undefined);
  await fireEvent.click(screen.getByRole('button', { name: 'Open account menu' }));
  expect(await screen.findByRole('menu')).toBeTruthy();
  expect(onNavigate).not.toHaveBeenCalled();
  for (const [name, href] of [
    ['Profile', '/profile'],
    ['Your workspaces', '/workspaces'],
    ['Settings', '/settings'],
    ['Security', '/settings/security'],
  ]) {
    expect(screen.getByRole('menuitem', { name }).getAttribute('href')).toBe(href);
  }
  await fireEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
  expect(signOut).toHaveBeenCalledOnce();
});
