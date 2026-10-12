import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import FileExplorer from '../../../src/web/src/ui/FileExplorer.svelte';

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
  expect(onopen).toHaveBeenCalledWith('proofs/lean/Main.lean', 'preview');
  expect(screen.queryByRole('button', { name: 'idea.md' })).toBeNull();
  await fireEvent.input(screen.getByLabelText('Find a file'), { target: { value: '' } });
  expect(screen.queryByRole('button', { name: 'Main.lean' })).toBeNull();
  expect(screen.getByRole('button', { name: 'README.md' })).toBeTruthy();
});

it('reveals a newly active nested file without reopening a manually collapsed folder', async () => {
  const result = render(FileExplorer, {
    props: { paths: ['src/a.py', 'src/b.py'], selected: 'src/a.py', onopen: vi.fn() },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'src' }));
  expect(screen.queryByRole('button', { name: 'a.py' })).toBeNull();
  await result.rerender({ paths: ['src/a.py', 'src/b.py', 'README.md'] });
  expect(screen.queryByRole('button', { name: 'a.py' })).toBeNull();
  await result.rerender({ selected: 'src/b.py' });
  expect((await screen.findByRole('button', { name: 'b.py' })).getAttribute('aria-current')).toBe(
    'page',
  );
});

it('respects a name filter until explicit reveal and opens permanently from the keyboard', async () => {
  const onopen = vi.fn();
  const onreveal = vi.fn();
  const result = render(FileExplorer, {
    props: { paths: ['a.py', 'b.py'], selected: '', onopen, onreveal },
  });
  await fireEvent.input(screen.getByLabelText('Find a file'), { target: { value: 'b.py' } });
  await result.rerender({ selected: 'a.py' });
  expect(screen.queryByRole('button', { name: 'a.py' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Reveal active file' }));
  expect(onreveal).toHaveBeenCalledOnce();
  await fireEvent.keyDown(await screen.findByRole('button', { name: 'a.py' }), { key: 'Enter' });
  expect(onopen).toHaveBeenLastCalledWith('a.py', 'permanent');
});
