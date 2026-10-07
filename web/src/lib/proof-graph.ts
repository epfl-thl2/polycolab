import type { Edge, Node } from '@xyflow/svelte';
import type { ProofSketchView } from './assurance-view';

export type ProofGraph = { nodes: Node[]; edges: Edge[] };

export function proofGraph(alternatives: ProofSketchView[]): ProofGraph {
  const nodes = new Map<string, Node>();
  const edges: Edge[] = [];

  alternatives.forEach((alternative, alternativeIndex) => {
    const row = alternativeIndex * 220;
    const proofId = `proof-sketch:${alternative.sketchId}`;
    const conclusionId = `statement:${alternative.conclusion.revisionId}`;
    nodes.set(proofId, {
      id: proofId,
      position: { x: 320, y: row },
      data: { label: alternative.title },
      style: 'width:210px; padding:12px; border:2px solid #45665f; background:#fffdf9;',
    });
    if (!nodes.has(conclusionId)) {
      nodes.set(conclusionId, {
        id: conclusionId,
        position: { x: 650, y: row },
        data: { label: alternative.conclusion.title },
        style: 'width:210px; padding:12px; border:2px solid #78562d; background:#fffdf9;',
      });
    }
    edges.push({
      id: `${proofId}->${conclusionId}`,
      source: proofId,
      target: conclusionId,
      label: 'concludes',
    });

    alternative.premises.forEach((premise, premiseIndex) => {
      const premiseId = `statement:${premise.revisionId}`;
      if (!nodes.has(premiseId)) {
        nodes.set(premiseId, {
          id: premiseId,
          position: { x: 0, y: row + premiseIndex * 80 },
          data: { label: premise.title },
          style: 'width:210px; padding:12px; border:1px solid #6f817d; background:#fffdf9;',
        });
      }
      edges.push({
        id: `${premiseId}->${proofId}`,
        source: premiseId,
        target: proofId,
        label: 'jointly required',
      });
    });
  });

  return { nodes: [...nodes.values()], edges };
}
