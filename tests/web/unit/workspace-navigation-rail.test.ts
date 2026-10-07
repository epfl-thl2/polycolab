import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import WorkspaceNavigationRail from '../../../web/src/ui/WorkspaceNavigationRail.svelte';
afterEach(cleanup);
function setup(extra = {}) {
  const onNavigate = vi.fn();
  const result = render(WorkspaceNavigationRail, {
    projectId: 'workspace',
    section: 'research',
    canManage: true,
    onNavigate,
    ...extra,
  });
  return { ...result, onNavigate };
}
it('uses explicit overview and workspace paths with the selected section', async () => {
  const { onNavigate } = setup();
  expect(screen.getByRole('link', { name: 'Research objects' }).getAttribute('aria-current')).toBe(
    'page',
  );
  await fireEvent.click(screen.getByRole('link', { name: 'Overview' }));
  expect(onNavigate).toHaveBeenCalledWith('/workspaces/workspace/overview');
  expect(
    screen.getByRole('complementary', { name: 'Workspace navigation' }).classList.contains('open'),
  ).toBe(false);
  expect(screen.getByRole('link', { name: 'Workspaces' }).getAttribute('href')).toBe('/workspaces');
  expect(screen.queryByRole('link', { name: 'Agents' })).toBeNull();
});
it('keeps the icon rail fixed on hover and keyboard focus with no pin control', async () => {
  const { container } = setup();
  const rail = screen.getByRole('complementary', { name: 'Workspace navigation' });
  await fireEvent.mouseEnter(rail);
  await fireEvent.focusIn(screen.getByRole('link', { name: 'Overview' }));
  expect(rail.classList.contains('open')).toBe(false);
  expect(container.querySelector('.rail-slot')?.classList.contains('reserved')).toBe(false);
  expect(screen.queryByRole('button', { name: /Pin workspace navigation/ })).toBeNull();
  expect(screen.getByRole('link', { name: 'Overview' }).getAttribute('title')).toBeNull();
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
