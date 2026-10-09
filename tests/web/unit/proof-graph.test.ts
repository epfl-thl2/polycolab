import { expect, it } from 'vitest';
import { proofGraph } from '../../../src/web/src/lib/proof-graph';
import type { ProofSketchView } from '../../../src/web/src/lib/assurance-view';

const alternative = (sketchId: string, premiseRevisionIds: string[]): ProofSketchView => ({
  sketchId,
  sketchRevisionId: `${sketchId}-r1`,
  recordKind: 'PROOF',
  title: sketchId,
  href: `/commons/records/${sketchId}`,
  author: 'Researcher',
  conclusion: {
    revisionId: 'conclusion-r1',
    title: 'Shared conclusion',
    href: '/commons/records/conclusion-r1',
  },
  premises: premiseRevisionIds.map((revisionId) => ({
    revisionId,
    title: revisionId,
    href: `/commons/records/${revisionId}`,
  })),
  reportedProgress: 'Unassessed',
  endorsement: 'UNASSESSED',
  correspondence: 'UNASSESSED',
  currentEndorsements: [],
  currentCorrespondence: [],
  endorsementHistory: [],
  correspondenceHistory: [],
  unresolvedAssumptions: [],
  machineObservations: [],
  historical: false,
});

it('projects alternative proofs as separate nodes and premise sets', () => {
  const graph = proofGraph([
    alternative('proof-a', ['premise-a', 'shared-premise']),
    alternative('proof-b', ['premise-b', 'shared-premise']),
  ]);

  expect(
    graph.nodes.filter((node) => node.id.startsWith('proof-sketch:')).map((node) => node.id),
  ).toEqual(['proof-sketch:proof-a', 'proof-sketch:proof-b']);
  expect(graph.nodes.filter((node) => node.id === 'statement:shared-premise')).toHaveLength(1);
  expect(graph.edges).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        source: 'statement:premise-a',
        target: 'proof-sketch:proof-a',
        label: 'jointly required',
      }),
      expect.objectContaining({
        source: 'statement:premise-b',
        target: 'proof-sketch:proof-b',
        label: 'jointly required',
      }),
      expect.objectContaining({
        source: 'proof-sketch:proof-a',
        target: 'statement:conclusion-r1',
        label: 'concludes',
      }),
      expect.objectContaining({
        source: 'proof-sketch:proof-b',
        target: 'statement:conclusion-r1',
        label: 'concludes',
      }),
    ]),
  );
  expect(
    graph.edges.some(
      (edge) => edge.source === 'statement:premise-a' && edge.target === 'proof-sketch:proof-b',
    ),
  ).toBe(false);
});
