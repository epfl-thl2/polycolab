import { displayRelationships } from './display-relationships';
import type { WorkspaceMap } from './workspace-map';
export function groupRelationships(data: WorkspaceMap | undefined, objectId: string) {
  type Item = {
    relation: WorkspaceMap['relations'][number];
    display: import('./display-relationships').DisplayRelationship;
    otherRevisionId: string;
    focusedRevisionId: string;
    direction: 'outgoing' | 'incoming' | 'bidirectional';
  };
  const groups = new Map<string, Item[]>();
  const revisions = new Set(
    data?.nodes.filter((node) => node.object_id === objectId).map((node) => node.object_version_id),
  );
  for (const edge of data ? displayRelationships(data) : []) {
    const outgoing = revisions.has(edge.parentVersionId);
    if (!outgoing && !revisions.has(edge.childVersionId)) continue;
    const label = outgoing ? edge.label : 'Referenced by';
    const items = groups.get(label) ?? [];
    items.push({
      relation: edge.originals[0],
      display: edge,
      direction: outgoing ? 'outgoing' : 'incoming',
      otherRevisionId: outgoing ? edge.childVersionId : edge.parentVersionId,
      focusedRevisionId: outgoing ? edge.parentVersionId : edge.childVersionId,
    });
    groups.set(label, items);
  }
  return [...groups]
    .map(([label, items]) => ({ label, items }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
