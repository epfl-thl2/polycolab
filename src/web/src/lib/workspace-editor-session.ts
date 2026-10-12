import type * as Monaco from 'monaco-editor';

export type PlainEditorView = {
  start: number;
  end: number;
  direction: 'forward' | 'backward' | 'none';
  top: number;
  left: number;
};

type EditorSession = {
  model?: Monaco.editor.ITextModel;
  view?: Monaco.editor.ICodeEditorViewState;
  plain?: PlainEditorView;
};

/** Owned by one workspace page; file contents and undo history never enter storage. */
export class WorkspaceEditorSessions {
  private entries = new Map<string, EditorSession>();
  private disposed = false;

  entry(key: string): EditorSession {
    let entry = this.entries.get(key);
    if (!entry) {
      entry = {};
      if (!this.disposed) this.entries.set(key, entry);
    }
    return entry;
  }

  model(monaco: typeof Monaco, key: string, value: string, language: string) {
    if (this.disposed) throw new Error('The workspace editor session has ended.');
    const entry = this.entry(key);
    if (!entry.model || entry.model.isDisposed())
      entry.model = monaco.editor.createModel(
        value,
        language,
        monaco.Uri.from({ scheme: 'polycolab', path: `/${key}` }),
      );
    return entry.model;
  }

  release(key: string) {
    this.entries.get(key)?.model?.dispose();
    this.entries.delete(key);
  }

  dispose() {
    this.disposed = true;
    for (const key of this.entries.keys()) this.release(key);
  }
}

/** Apply an external update as an undoable edit, retaining unchanged prefixes/suffixes. */
export function syncEditorModel(model: Monaco.editor.ITextModel, value: string) {
  const current = model.getValue();
  const normalized = value.replace(/\r\n|\r|\n/g, model.getEOL());
  if (current === normalized) return;
  let start = 0;
  while (
    start < current.length &&
    start < normalized.length &&
    current[start] === normalized[start]
  )
    start++;
  let end = current.length;
  let nextEnd = normalized.length;
  while (end > start && nextEnd > start && current[end - 1] === normalized[nextEnd - 1]) {
    end--;
    nextEnd--;
  }
  const from = model.getPositionAt(start);
  const to = model.getPositionAt(end);
  model.pushStackElement();
  model.pushEditOperations(
    null,
    [
      {
        range: {
          startLineNumber: from.lineNumber,
          startColumn: from.column,
          endLineNumber: to.lineNumber,
          endColumn: to.column,
        },
        text: normalized.slice(start, nextEnd),
      },
    ],
    () => null,
  );
  model.pushStackElement();
}
