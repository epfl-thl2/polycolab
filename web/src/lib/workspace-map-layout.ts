import { relationshipChoices, type DisplayRelationshipKind } from './display-relationships';
import { canonicalObjectKind } from './object-kind';
import { relationshipEndpoints } from './relationship-view';
import type { ElkNode, ELK } from 'elkjs/lib/elk-api';
import type { WorkspaceMap } from './workspace-map';
export type Point = { x: number; y: number };
export type MapNodeSize = { width: number; height: number };
export type MapLayout = {
  positions: Record<string, Point>;
  sizes: Record<string, MapNodeSize>;
  routes: Record<string, { points: Point[]; label: Point }>;
  width: number;
  height: number;
};

export function mapNodeSize(kind?: string): MapNodeSize {
  switch (canonicalObjectKind(kind ?? '')) {
    case 'PROOF':
      return { width: 140, height: 88 };
    case 'NOTE':
      return { width: 172, height: 56 };
    case 'ATTEMPT':
      return { width: 192, height: 60 };
    case 'STATEMENT':
    case 'DEFINITION':
    case 'FORMALIZATION':
      return { width: 208, height: 64 };
    default:
      return { width: 220, height: 64 };
  }
}

export async function layoutWorkspaceMap(
  data: WorkspaceMap,
  engine: Pick<ELK, 'layout'>,
): Promise<MapLayout> {
  const ids = new Set(data.nodes.map((node) => node.object_version_id));
  const kindByObject = new Map(data.objects.map((object) => [object.id, object.kind]));
  const sizes: MapLayout['sizes'] = Object.create(null);
  for (const node of data.nodes)
    sizes[node.object_version_id] = mapNodeSize(kindByObject.get(node.object_id));
  const graph: ElkNode = {
    id: 'workspace',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.spacing.nodeNode': '40',
      'elk.layered.spacing.nodeNodeBetweenLayers': '100',
      'elk.layered.spacing.edgeNodeBetweenLayers': '24',
      'elk.spacing.edgeNode': '20',
      'elk.padding': '[top=24,left=24,bottom=24,right=24]',
      'elk.separateConnectedComponents': 'true',
      'elk.randomSeed': '1',
    },
    children: [...data.nodes]
      .sort((a, b) => a.object_version_id.localeCompare(b.object_version_id))
      .map((node) => ({
        id: node.object_version_id,
        width: sizes[node.object_version_id].width,
        height: sizes[node.object_version_id].height,
        layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE' },
        ports: [
          { id: `${node.object_version_id}:in`, layoutOptions: { 'elk.port.side': 'NORTH' } },
          { id: `${node.object_version_id}:out`, layoutOptions: { 'elk.port.side': 'SOUTH' } },
        ],
      })),
    edges: [...data.relations]
      .filter(
        (edge) =>
          ids.has(relationshipEndpoints(edge)[0]) && ids.has(relationshipEndpoints(edge)[1]),
      )
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((edge) => ({
        id: edge.id,
        sources: [`${relationshipEndpoints(edge)[0]}:out`],
        targets: [`${relationshipEndpoints(edge)[1]}:in`],
        labels: [
          {
            text:
              relationshipChoices[edge.relationship_type as DisplayRelationshipKind] ??
              edge.relationship_type,
            width: edge.relationship_type.length * 6.5,
            height: 18,
          },
        ],
      })),
  };
  const result = await engine.layout(graph);
  const positions: MapLayout['positions'] = Object.create(null);
  const routes: MapLayout['routes'] = Object.create(null);
  for (const node of result.children ?? []) positions[node.id] = { x: node.x ?? 0, y: node.y ?? 0 };
  for (const edge of result.edges ?? []) {
    const section = edge.sections?.[0];
    if (!section) continue;
    const points = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
    const label = edge.labels?.[0];
    routes[edge.id] = {
      points,
      label:
        label?.x !== undefined && label.y !== undefined
          ? { x: label.x + (label.width ?? 0) / 2, y: label.y + (label.height ?? 0) / 2 }
          : points[Math.floor(points.length / 2)],
    };
  }
  return { positions, sizes, routes, width: result.width ?? 0, height: result.height ?? 0 };
}

/** Round orthogonal corners without leaving the routing corridor. */
export function roundedRoute(points: Point[], radius = 8): string {
  if (!points.length) return '';
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1],
      point = points[i],
      next = points[i + 1];
    const incoming = Math.hypot(point.x - prev.x, point.y - prev.y);
    const outgoing = Math.hypot(next.x - point.x, next.y - point.y);
    if (!incoming || !outgoing) continue;
    const r = Math.min(radius, incoming / 2, outgoing / 2);
    path += ` L ${point.x + ((prev.x - point.x) * r) / incoming} ${point.y + ((prev.y - point.y) * r) / incoming}`;
    path += ` Q ${point.x} ${point.y} ${point.x + ((next.x - point.x) * r) / outgoing} ${point.y + ((next.y - point.y) * r) / outgoing}`;
  }
  const end = points[points.length - 1];
  return `${path} L ${end.x} ${end.y}`;
}
