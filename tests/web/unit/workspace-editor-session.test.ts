import { expect, it, vi } from 'vitest';
import {
  WorkspaceEditorSessions,
  syncEditorModel,
} from '../../../src/web/src/lib/workspace-editor-session';
import { fileDecorations } from '../../../src/web/src/lib/file-explorer';

it('isolates models by worktree, retains open models, and disposes closed sessions', () => {
  const created: Array<{ dispose: ReturnType<typeof vi.fn>; isDisposed: () => boolean }> = [];
  const engine = {
    Uri: { from: vi.fn((uri) => uri) },
    editor: {
      createModel: vi.fn(() => {
        let disposed = false;
        const model = {
          dispose: vi.fn(() => {
            disposed = true;
          }),
          isDisposed: () => disposed,
        };
        created.push(model);
        return model;
      }),
    },
  } as unknown as Parameters<WorkspaceEditorSessions['model']>[0];
  const sessions = new WorkspaceEditorSessions();
  const first = sessions.model(engine, 'project/main/file', 'main text', 'plaintext');
  expect(sessions.model(engine, 'project/main/file', 'main text', 'plaintext')).toBe(first);
  expect(sessions.model(engine, 'project/branch/file', 'branch text', 'plaintext')).not.toBe(first);
  sessions.release('project/main/file');
  expect(created[0]!.dispose).toHaveBeenCalledOnce();
  expect(created[1]!.dispose).not.toHaveBeenCalled();
  sessions.dispose();
  expect(created[1]!.dispose).toHaveBeenCalledOnce();
  expect(() => sessions.model(engine, 'project/main/file', '', 'plaintext')).toThrow('ended');
});

it('leaves unchanged content alone and applies external edits without replacing the model', () => {
  const push = vi.fn();
  const stop = vi.fn();
  const model = {
    getValue: () => 'before middle after',
    getEOL: () => '\n',
    getPositionAt: (offset: number) => ({ lineNumber: 1, column: offset + 1 }),
    pushStackElement: stop,
    pushEditOperations: push,
  } as unknown as Parameters<typeof syncEditorModel>[0];
  syncEditorModel(model, 'before middle after');
  expect(push).not.toHaveBeenCalled();
  syncEditorModel(model, 'before new after');
  expect(push.mock.calls[0]![1]).toEqual([
    {
      range: { startLineNumber: 1, startColumn: 8, endLineNumber: 1, endColumn: 14 },
      text: 'new',
    },
  ]);
  expect(stop).toHaveBeenCalledTimes(2);
});

it('aggregates saved changes into existing folders without inventing deleted files', () => {
  const changes = fileDecorations(
    ['src/new.py', 'src/changed.py', 'other.py'],
    [
      { path: 'src/new.py', status: 'added' },
      { path: 'src/changed.py', status: 'modified' },
      { path: 'src/deleted.py', status: 'deleted' },
      { path: 'removed/file.py', status: 'deleted' },
    ],
  );
  expect(changes.get('src')).toBe('deleted');
  expect(changes.get('src/new.py')).toBe('added');
  expect(changes.get('src/changed.py')).toBe('modified');
  expect(changes.has('src/deleted.py')).toBe(false);
  expect(changes.has('removed')).toBe(false);
  expect(fileDecorations(['src/new.py'], []).size).toBe(0);
});
