import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { Auth } from '../../../src/web/src/svelte-lib/auth.svelte';
import ProjectNavigationRail from '../../../src/web/src/ui/ProjectNavigationRail.svelte';
afterEach(cleanup);
function setup(extra = {}) {
  const onNavigate = vi.fn();
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: true, username: 'ada', display_name: 'Ada Lovelace' };
  auth.loaded = true;
  const result = render(ProjectNavigationRail, {
    auth,
    projectId: 'project',
    section: 'research',
    canManage: true,
    onNavigate,
    ...extra,
  });
  return { ...result, onNavigate, auth };
}
it('uses explicit overview and project paths with the selected section', async () => {
  const { onNavigate } = setup();
  expect(screen.getByRole('link', { name: 'Research objects' }).getAttribute('aria-current')).toBe(
    'page',
  );
  await fireEvent.click(screen.getByRole('link', { name: 'Overview' }));
  expect(onNavigate).toHaveBeenCalledWith('/projects/project/overview');
  await fireEvent.click(screen.getByRole('link', { name: /^Project$/ }));
  expect(onNavigate).toHaveBeenCalledWith('/projects/project/sessions');
  expect(
    screen.getByRole('complementary', { name: 'Project navigation' }).classList.contains('open'),
  ).toBe(false);
  expect(screen.getByRole('button', { name: 'Open account menu' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Agents' })).toBeNull();
});
it('keeps the icon rail fixed on hover and keyboard focus with no pin control', async () => {
  const { container } = setup();
  const rail = screen.getByRole('complementary', { name: 'Project navigation' });
  await fireEvent.mouseEnter(rail);
  await fireEvent.focusIn(screen.getByRole('link', { name: 'Overview' }));
  expect(rail.classList.contains('open')).toBe(false);
  expect(container.querySelector('.rail-slot')?.classList.contains('reserved')).toBe(false);
  expect(screen.queryByRole('button', { name: /Pin project navigation/ })).toBeNull();
  expect(screen.getByRole('link', { name: 'Overview' }).getAttribute('title')).toBeNull();
});
it('shows the mobile drawer expanded and limits project management links', () => {
  setup({ expanded: true, canManage: false });
  const rail = screen.getByRole('complementary', { name: 'Project navigation' });
  expect(rail.classList.contains('open')).toBe(true);
  expect(screen.queryByRole('button', { name: 'Pin project navigation' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Project settings' })).toBeNull();
  expect(screen.getByRole('link', { name: 'Agent connect' })).toBeTruthy();
});
it('preserves modified clicks for opening navigation in another tab', async () => {
  const { onNavigate } = setup();
  await fireEvent.click(screen.getByRole('link', { name: 'Map' }), { ctrlKey: true });
  expect(onNavigate).not.toHaveBeenCalled();
});

it('opens the shared account menu without leaving the project and supports sign out', async () => {
  const { onNavigate, auth } = setup();
  const signOut = vi.spyOn(auth, 'signOut').mockResolvedValue(undefined);
  await fireEvent.click(screen.getByRole('button', { name: 'Open account menu' }));
  expect(await screen.findByRole('menu')).toBeTruthy();
  expect(onNavigate).not.toHaveBeenCalled();
  for (const [name, href] of [
    ['Profile', '/profile'],
    ['Your projects', '/projects'],
    ['Settings', '/settings'],
    ['Password and authentication', '/settings/security'],
  ]) {
    expect(screen.getByRole('menuitem', { name }).getAttribute('href')).toBe(href);
  }
  await fireEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
  expect(signOut).toHaveBeenCalledOnce();
});
