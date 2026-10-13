import { expect, it, vi } from 'vitest';
import { LinearSession } from '../../../src/web/src/lib/linear-session';
import type { LinearDocument } from '../../../src/web/src/lib/linear-api';

it('shares a document when file preview and double-click overlap', async () => {
  const live = new LinearSession(
    'project',
    async () => undefined,
    () => {},
  );
  live.state = {
    epoch: 1,
    sequence: 0,
    writable: true,
    can_restore: true,
    has_git_archive: false,
    files: [],
  };
  let finish!: (document: LinearDocument) => void;
  const request = new Promise<LinearDocument>((resolve) => {
    finish = resolve;
  });
  vi.spyOn(live.api, 'file').mockReturnValue(request);
  vi.spyOn(live.api, 'history').mockResolvedValue([]);
  const preview = live.open('file');
  const permanent = live.open('file');
  finish({
    id: 'file',
    path: 'notes.txt',
    executable: false,
    epoch: 1,
    sequence: 0,
    deleted: false,
    content_base64: '',
    document: 'AAA=',
  });
  const [first, second] = await Promise.all([preview, permanent]);
  try {
    first.doc.getText('content').insert(0, 'Shared text');
    expect(second.doc.getText('content').toString()).toBe('Shared text');
    expect(await live.open('file')).toBe(first);
    expect(live.api.file).toHaveBeenCalledOnce();
  } finally {
    live.destroy();
  }
});
