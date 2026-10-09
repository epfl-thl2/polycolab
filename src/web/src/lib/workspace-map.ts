import { displayRelationships } from './display-relationships';
import { canonicalObjectKind } from './object-kind';
import { relationshipEndpoints } from './relationship-view';
import type {
  ResearchApi,
  ResearchObject,
  PublicResearchObject,
  NeighborhoodNode,
  Relation,
  PublicRelation,
  Page,
} from './research-api';

export type MapObject = ResearchObject | PublicResearchObject;
export type WorkspaceMap = {
  objects: MapObject[];
  nodes: (NeighborhoodNode & {
    object_version_number?: number;
    proof_direction?: 'SUPPORTS' | 'REFUTES';
  })[];
  relations: (Relation | PublicRelation)[];
};

async function allPages<T>(fetch: (cursor?: string) => Promise<Page<T>>): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  do {
    const page = await fetch(cursor);
    items.push(...page.items);
    cursor = page.nextCursor;
  } while (cursor);
  return items;
}

/** Traverse bounded endpoints with at most four objects being fetched concurrently. */
export async function loadWorkspaceMap(
  api: ResearchApi,
  projectId: string,
  publicRead = false,
): Promise<WorkspaceMap> {
  const objects = await allPages((cursor) => api.listObjects(projectId, publicRead, cursor));
  const relations = new Map<string, Relation | PublicRelation>();
  const revisions = new Map<string, WorkspaceMap['nodes'][number]>(
    objects.map((object) => [
      object.current_object_version.id,
      {
        object_version_id: object.current_object_version.id,
        object_id: object.id,
        title: object.current_object_version.content.title,
        object_version_number: object.current_object_version.number,
        proof_direction:
          object.current_object_version.kind === 'PROOF'
            ? (object.current_object_version.content.direction ?? 'SUPPORTS')
            : undefined,
      },
    ]),
  );
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(4, objects.length) }, async () => {
      while (next < objects.length) {
        const object = objects[next++];
        const links = await allPages((cursor) =>
          api.listRelations(projectId, object.id, publicRead, cursor),
        );
        for (const relation of links) relations.set(relation.id, relation);
        if (
          links.some(
            (link) =>
              !revisions.has(relationshipEndpoints(link)[0]) ||
              !revisions.has(relationshipEndpoints(link)[1]),
          )
        ) {
          for (const revision of await allPages((cursor) =>
            api.listVersions(projectId, object.id, publicRead, cursor),
          )) {
            revisions.set(revision.id, {
              object_version_id: revision.id,
              object_id: object.id,
              title: revision.content.title,
              object_version_number: revision.number,
              proof_direction:
                revision.kind === 'PROOF' ? (revision.content.direction ?? 'SUPPORTS') : undefined,
            });
          }
        }
      }
    }),
  );
  const used = new Set(objects.map((object) => object.current_object_version.id));
  for (const relation of relations.values()) {
    used.add(relationshipEndpoints(relation)[0]);
    used.add(relationshipEndpoints(relation)[1]);
  }
  return {
    objects,
    nodes: [...revisions.values()].filter((node) => used.has(node.object_version_id)),
    relations: [...relations.values()],
  };
}

/** All terms match; quotes preserve phrases and a leading minus excludes a term. */
export function searchMapObjects(objects: MapObject[], query: string): MapObject[] {
  const normalize = (value: string) =>
    value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase();
  const terms = [...normalize(query).matchAll(/(-?)(?:"([^"]+)"|(\S+))/g)].map((match) => ({
    exclude: match[1] === '-',
    text: match[2] ?? match[3],
  }));
  return objects
    .filter((object) => {
      const text = normalize(
        `${object.current_object_version.content.title} ${object.current_object_version.content.content_md} ${object.kind} ${object.id} ${object.current_object_version.id}`,
      );
      return terms.every((term) =>
        term.exclude ? !text.includes(term.text) : text.includes(term.text),
      );
    })
    .sort((a, b) => {
      const exact = normalize(query.trim());
      return (
        Number(normalize(b.current_object_version.content.title) === exact) -
          Number(normalize(a.current_object_version.content.title) === exact) ||
        a.current_object_version.content.title.localeCompare(b.current_object_version.content.title)
      );
    });
}

/** Notes, attempts and formalizations belong in an object's inspector, not in the diagram. */
export function diagramObjects(data: WorkspaceMap): WorkspaceMap {
  const objects = data.objects.filter(
    (object) => !['NOTE', 'ATTEMPT', 'FORMALIZATION'].includes(canonicalObjectKind(object.kind)),
  );
  const objectIds = new Set(objects.map((object) => object.id));
  const nodes = data.nodes.filter((node) => objectIds.has(node.object_id));
  const versions = new Set(nodes.map((node) => node.object_version_id));
  return {
    objects,
    nodes,
    relations: data.relations.filter((relation) =>
      relationshipEndpoints(relation).every((id) => versions.has(id)),
    ),
  };
}

/** Object-level display projection only; raw map data retains exact version pins. */
export function objectDiagram(data: WorkspaceMap): WorkspaceMap {
  const filtered = diagramObjects(data);
  const heads = new Map(
    filtered.objects.map((object) => [object.id, object.current_object_version.id]),
  );
  const endpoints = new Map(
    filtered.nodes.map((node) => [node.object_version_id, heads.get(node.object_id)!]),
  );
  const seen = new Set<string>();
  const relations: WorkspaceMap['relations'] = [];
  for (const edge of displayRelationships(filtered)) {
    const first = endpoints.get(edge.parentVersionId);
    const second = endpoints.get(edge.childVersionId);
    if (!first || !second || first === second) continue;
    const key = JSON.stringify([edge.kind, first, second]);
    if (seen.has(key)) continue;
    seen.add(key);
    const original = edge.originals[0];
    if (original.direction !== 'UNIDIRECTIONAL') continue;
    relations.push({
      ...original,
      relationship_type: edge.kind,
      source_object_version_id: first,
      target_object_version_id: second,
    });
  }
  return {
    objects: filtered.objects,
    nodes: filtered.objects.map((object) => ({
      object_id: object.id,
      object_version_id: object.current_object_version.id,
      title: object.current_object_version.content.title,
      object_version_number: object.current_object_version.number,
    })),
    relations,
  };
}

/** Resolve historical pins to stable identities so later parent versions retain their context. */
export function attachedObjects(
  data: WorkspaceMap | undefined,
  objectId: string,
  kind: 'NOTE' | 'ATTEMPT',
): MapObject[] {
  if (!data) return [];
  const identities = new Map(data.nodes.map((node) => [node.object_version_id, node.object_id]));
  return data.objects.filter((object) => {
    if (canonicalObjectKind(object.kind) !== kind || object.id === objectId) return false;
    return (
      (object.current_object_version.content.attached_object_ids ?? []).includes(objectId) ||
      (object.current_object_version.structural_relationships ?? []).some(
        (pin) =>
          ['ATTACHMENT', 'TARGET'].includes(pin.relationship_type) &&
          identities.get(pin.target_object_version_id) === objectId,
      ) ||
      data.relations.some(
        (relation) =>
          relation.direction === 'UNIDIRECTIONAL' &&
          ['ATTACHMENT', 'TARGET'].includes(relation.relationship_type) &&
          identities.get(relation.source_object_version_id) === object.id &&
          identities.get(relation.target_object_version_id) === objectId,
      )
    );
  });
}

/** Formalizations are scoped to the selected exact version, never its stable identity. */
export function versionFormalizations(
  data: WorkspaceMap | undefined,
  versionId: string,
): MapObject[] {
  if (!data || !versionId) return [];
  return data.objects.filter(
    (object) =>
      canonicalObjectKind(object.kind) === 'FORMALIZATION' &&
      (object.current_object_version.structural_relationships.some(
        (pin) =>
          pin.relationship_type === 'ATTACHMENT' && pin.target_object_version_id === versionId,
      ) ||
        data.relations.some(
          (relation) =>
            relation.direction === 'UNIDIRECTIONAL' &&
            relation.relationship_type === 'ATTACHMENT' &&
            relation.source_object_version_id === object.current_object_version.id &&
            relation.target_object_version_id === versionId,
        )),
  );
}
