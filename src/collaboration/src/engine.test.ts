import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as Y from 'yjs';
import { prepare } from './engine.ts';
const encoded = (doc: Y.Doc, vector?: Uint8Array) =>
  Buffer.from(Y.encodeStateAsUpdate(doc, vector)).toString('base64');

test('concurrent writers converge and retries are idempotent', () => {
  const initial = prepare({ text: 'lemma' });
  const alice = new Y.Doc(),
    bob = new Y.Doc();
  for (const doc of [alice, bob]) Y.applyUpdate(doc, Buffer.from(initial.state, 'base64'));
  const vector = Y.encodeStateVector(alice);
  alice.getText('content').insert(0, 'A ');
  bob.getText('content').insert(5, ' B');
  const first = prepare({ state: initial.state, update: encoded(alice, vector) });
  const final = prepare({ state: first.state, update: encoded(bob, vector) });
  assert.equal(final.text, 'A lemma B');
  assert.equal(prepare({ state: final.state, update: encoded(alice, vector) }).text, final.text);
  assert.equal(prepare({ state: first.state, text: 'A theorem' }).text, 'A theorem');
});

test('an invalid candidate cannot mutate committed state', () => {
  const initial = prepare({ text: 'private' });
  const invalid = new Y.Doc();
  invalid.getMap('permissions').set('owner', true);
  assert.throws(() => prepare({ state: initial.state, update: encoded(invalid) }));
  assert.equal(prepare({ state: initial.state }).text, 'private');
});
