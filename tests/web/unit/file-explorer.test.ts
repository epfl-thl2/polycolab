import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import FileExplorer from '../../../web/src/ui/FileExplorer.svelte';

afterEach(cleanup);
it('groups nested paths into folders, keeps collapsed folders, and finds nested files', async () => {
  const onopen = vi.fn();
  render(FileExplorer, {
    props: { paths: ['notes/idea.md', 'proofs/lean/Main.lean', 'README.md'], onopen },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'proofs' }));
  expect(screen.queryByRole('button', { name: 'Main.lean' })).toBeNull();
  await fireEvent.input(screen.getByLabelText('Find a file'), { target: { value: 'main' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Main.lean' }));
  expect(onopen).toHaveBeenCalledWith('proofs/lean/Main.lean');
  expect(screen.queryByRole('button', { name: 'idea.md' })).toBeNull();
  await fireEvent.input(screen.getByLabelText('Find a file'), { target: { value: '' } });
  expect(screen.queryByRole('button', { name: 'Main.lean' })).toBeNull();
  expect(screen.getByRole('button', { name: 'README.md' })).toBeTruthy();
});
