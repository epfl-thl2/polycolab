import * as Y from 'yjs';
import { diffChars } from 'diff';

export type DocumentChange = { state?: string; update?: string; text?: string };
export type PreparedDocument = { state: string; update: string; text: string };
const MAX_BYTES = 16 * 1024 * 1024;

function decode(value: string): Uint8Array {
  if (
    value.length > MAX_BYTES * 4 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)
  )
    throw new Error('invalid_document_update');
  return Buffer.from(value, 'base64');
}

/** Prepare on a disposable document. Only the API may accept and persist the result. */
export function prepare(change: DocumentChange): PreparedDocument {
  const doc = new Y.Doc();
  try {
    const content = doc.getText('content');
    if (change.state) Y.applyUpdate(doc, decode(change.state));
    const before = Y.encodeStateVector(doc);
    if (change.update !== undefined) Y.applyUpdate(doc, decode(change.update));
    if (change.text !== undefined) {
      if (Buffer.byteLength(change.text) > MAX_BYTES) throw new Error('file_too_large');
      const changes = diffChars(content.toString(), change.text, { timeout: 1000 });
      if (!changes) throw new Error('text_diff_limit');
      doc.transact(() => {
        let position = 0;
        for (const part of changes) {
          if (part.removed) content.delete(position, part.value.length);
          else {
            if (part.added) content.insert(position, part.value);
            position += part.value.length;
          }
        }
      });
    }
    if (
      doc.share.size !== 1 ||
      !doc.share.has('content') ||
      content
        .toDelta()
        .some(
          (part: { insert?: unknown; attributes?: unknown }) =>
            typeof part.insert !== 'string' || part.attributes,
        ) ||
      doc.store.pendingStructs ||
      doc.store.pendingDs
    )
      throw new Error('invalid_document_shape');
    const text = content.toString();
    if (Buffer.byteLength(text) > MAX_BYTES) throw new Error('file_too_large');
    const state = Y.encodeStateAsUpdate(doc);
    if (state.byteLength > MAX_BYTES * 2) throw new Error('document_too_large');
    return {
      state: Buffer.from(state).toString('base64'),
      update: Buffer.from(Y.encodeStateAsUpdate(doc, before)).toString('base64'),
      text,
    };
  } finally {
    doc.destroy();
  }
}
