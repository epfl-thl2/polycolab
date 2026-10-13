import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ProjectTabStrip from '../../../src/web/src/ui/ProjectTabStrip.svelte';
import type { ProjectTab } from '../../../src/web/src/lib/project-tabs';
afterEach(cleanup);
const tabs: ProjectTab[] = [
  { id: 'chat', kind: 'chat', label: 'New chat', href: '/sessions/new' },
  { id: 'file', kind: 'file', label: 'proof.lean', href: '/files', dirty: true },
  { id: 'object', kind: 'object', label: 'Lemma', href: '/objects/lemma' },
];
function setup() {
  const callbacks = { onselect: vi.fn(), onclose: vi.fn(), onreorder: vi.fn(), onnewchat: vi.fn() };
  const result = render(ProjectTabStrip, { tabs, activeId: 'chat', ...callbacks });
  return { ...result, ...callbacks };
}
it('selects tabs and delegates close without selecting the closed tab', async () => {
  const { onselect, onclose } = setup();
  expect(screen.getByRole('tab', { name: 'New chat' }).getAttribute('aria-selected')).toBe('true');
  expect(screen.getByRole('tab', { name: /proof.lean/ }).getAttribute('tabindex')).toBe('-1');
  await fireEvent.click(screen.getByRole('tab', { name: 'Lemma' }));
  expect(onselect).toHaveBeenCalledWith('object');
  onselect.mockClear();
  await fireEvent.click(screen.getByRole('button', { name: 'Close proof.lean' }));
  expect(onclose).toHaveBeenCalledWith('file');
  expect(onselect).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Unsaved changes')).toBeTruthy();
});
it('moves selection and focus with arrows, Home, and End including wraparound', async () => {
  const { onselect } = setup();
  const first = screen.getByRole('tab', { name: 'New chat' });
  await fireEvent.keyDown(first, { key: 'ArrowRight' });
  expect(onselect).toHaveBeenLastCalledWith('file');
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: /proof.lean/ })),
  );
  await fireEvent.keyDown(first, { key: 'ArrowLeft' });
  expect(onselect).toHaveBeenLastCalledWith('object');
  await fireEvent.keyDown(first, { key: 'End' });
  expect(onselect).toHaveBeenLastCalledWith('object');
  await fireEvent.keyDown(screen.getByRole('tab', { name: 'Lemma' }), { key: 'Home' });
  expect(onselect).toHaveBeenLastCalledWith('chat');
});
it('reorders with Alt and arrows without changing selection or wrapping past the edge', async () => {
  const { onreorder, onselect } = setup();
  await fireEvent.keyDown(screen.getByRole('tab', { name: /proof.lean/ }), {
    key: 'ArrowLeft',
    altKey: true,
  });
  expect(onreorder).toHaveBeenLastCalledWith(['file', 'chat', 'object']);
  await fireEvent.keyDown(screen.getByRole('tab', { name: /proof.lean/ }), {
    key: 'ArrowRight',
    altKey: true,
  });
  expect(onreorder).toHaveBeenLastCalledWith(['chat', 'object', 'file']);
  await fireEvent.keyDown(screen.getByRole('tab', { name: 'New chat' }), {
    key: 'ArrowLeft',
    altKey: true,
  });
  expect(onreorder).toHaveBeenCalledTimes(2);
  expect(onselect).not.toHaveBeenCalled();
});
it('adds a chat through the supplied callback and reorders dragged tabs', async () => {
  const { onnewchat, onreorder } = setup();
  await fireEvent.click(screen.getByRole('button', { name: 'New chat tab' }));
  expect(onnewchat).toHaveBeenCalledOnce();
  await fireEvent.dragStart(screen.getByRole('tab', { name: 'Lemma' }));
  await fireEvent.drop(screen.getByRole('tab', { name: 'New chat' }));
  expect(onreorder).toHaveBeenCalledWith(['object', 'chat', 'file']);
});
