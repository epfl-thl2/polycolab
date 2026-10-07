import { expect, it } from 'vitest';
import { objectKindVisual } from '../../../web/src/lib/object-kind-visual';
import { mapNodeShape } from '../../../web/src/lib/map-node-shape';
import { mapNodeSize } from '../../../web/src/lib/workspace-map-layout';

it.each([
  ['CLAIM', 'STATEMENT', 'Statement'],
  ['PROOF_SKETCH', 'PROOF', 'Proof'],
  ['IDEA', 'NOTE', 'Note'],
  ['DISCUSSION', 'NOTE', 'Note'],
  ['COUNTEREXAMPLE', 'NOTE', 'Note'],
  ['COMPUTATION', 'NOTE', 'Note'],
])('renders historical %s with canonical %s visuals', (legacy, canonical, label) => {
  expect(objectKindVisual(legacy)).toEqual(objectKindVisual(canonical));
  expect(objectKindVisual(legacy).label).toBe(label);
  expect(mapNodeShape(legacy)).toBe(mapNodeShape(canonical));
  expect(mapNodeSize(legacy)).toEqual(mapNodeSize(canonical));
});
