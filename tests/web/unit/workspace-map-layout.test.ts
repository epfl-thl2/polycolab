import { describe, expect, it } from 'vitest';
import { relationshipEndpoints } from '../../../src/web/src/lib/relationship-view';
import ELK from '../../../src/web/node_modules/elkjs/lib/elk.bundled.js';
import {
  layoutWorkspaceMap,
  mapNodeSize,
  roundedRoute,
} from '../../../src/web/src/lib/workspace-map-layout';
import type { WorkspaceMap } from '../../../src/web/src/lib/workspace-map';
const graph = (links: [string, string][]): WorkspaceMap => ({
  objects: [],
  nodes: ['a', 'b', 'c', 'd', 'isolated'].map((id) => ({
    object_version_id: id,
    object_id: id,
    title: id,
  })),
  relations: links.map(([source, target], index) => ({
    id: `edge-${index}`,
    source_object_version_id: source,
    target_object_version_id: target,
    relationship_type: 'DEPENDS_ON',
  })) as WorkspaceMap['relations'],
});

describe('ELK workspace layout', () => {
  it('layers a DAG, retains isolated nodes, and routes clear of other node interiors', async () => {
    const data = graph([
      ['a', 'b'],
      ['a', 'c'],
      ['b', 'd'],
      ['c', 'd'],
    ]);
    const layout = await layoutWorkspaceMap(data, new ELK());
    expect(Object.keys(layout.positions)).toHaveLength(5);
    for (const edge of data.relations) {
      expect(layout.positions[relationshipEndpoints(edge)[0]].y).toBeLessThan(
        layout.positions[relationshipEndpoints(edge)[1]].y,
      );
      const points = layout.routes[edge.id].points;
      for (let i = 1; i < points.length; i++) {
        const a = points[i - 1],
          b = points[i];
        expect(a.x === b.x || a.y === b.y).toBe(true);
        for (const [id, node] of Object.entries(layout.positions)) {
          if ([relationshipEndpoints(edge)[0], relationshipEndpoints(edge)[1]].includes(id))
            continue;
          const crosses =
            a.x === b.x
              ? a.x > node.x &&
                a.x < node.x + layout.sizes[id].width &&
                Math.max(a.y, b.y) > node.y &&
                Math.min(a.y, b.y) < node.y + layout.sizes[id].height
              : a.y > node.y &&
                a.y < node.y + layout.sizes[id].height &&
                Math.max(a.x, b.x) > node.x &&
                Math.min(a.x, b.x) < node.x + layout.sizes[id].width;
          expect(crosses).toBe(false);
        }
      }
    }
    expect(await layoutWorkspaceMap(data, new ELK())).toEqual(layout);
  });
  it('sizes proofs below statements and routes to their actual edges', async () => {
    const data = graph([['a', 'b']]);
    data.objects = [
      { id: 'a', kind: 'STATEMENT' },
      { id: 'b', kind: 'PROOF' },
    ] as WorkspaceMap['objects'];
    const layout = await layoutWorkspaceMap(data, new ELK());
    expect(layout.sizes.a).toEqual(mapNodeSize('STATEMENT'));
    expect(layout.sizes.b).toEqual(mapNodeSize('PROOF'));
    expect(layout.sizes.b.width).toBeLessThan(layout.sizes.a.width);
    expect(layout.sizes.b).toEqual({ width: 140, height: 88 });
    expect(layout.routes['edge-0'].points[0].y).toBe(layout.positions.a.y + layout.sizes.a.height);
    expect(layout.routes['edge-0'].points.at(-1)!.y).toBe(layout.positions.b.y);
  });
  it('keeps cycles, parallel relationships, and self loops with original direction', async () => {
    const data = graph([
      ['a', 'b'],
      ['b', 'a'],
      ['a', 'b'],
      ['c', 'c'],
    ]);
    const layout = await layoutWorkspaceMap(data, new ELK());
    expect(Object.keys(layout.routes)).toHaveLength(4);
    for (const edge of data.relations) {
      const route = layout.routes[edge.id];
      expect(route.points[0].y).toBe(
        layout.positions[relationshipEndpoints(edge)[0]].y +
          layout.sizes[relationshipEndpoints(edge)[0]].height,
      );
      expect(route.points.at(-1)!.y).toBe(layout.positions[relationshipEndpoints(edge)[1]].y);
      expect(roundedRoute(route.points)).not.toContain('NaN');
    }
  });
});
