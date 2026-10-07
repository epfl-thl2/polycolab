import { structuralPin } from './version-fixtures';
import { describe, expect, it, vi } from 'vitest';
import {
  loadWorkspaceMap,
  objectDiagram,
  versionFormalizations,
  type WorkspaceMap,
  searchMapObjects,
  type MapObject,
} from '../../../web/src/lib/workspace-map';
import type { ResearchApi } from '../../../web/src/lib/research-api';

const object = (id: string, title: string, content = '') =>
  ({
    id,
    kind: 'STATEMENT',
    current_object_version: {
      id: `${id}-current`,
      content: { title, content_md: content },
      number: 2,
    },
  }) as MapObject;

describe('workspace map', () => {
  it('searches content, phrases, combined terms, exclusions, kinds, and exact IDs', () => {
    const objects = [
      object('a', 'Spectral gaps', 'Finite expander graphs'),
      object('b', 'Spectral theory', 'Infinite graphs'),
      object('c', 'Café lemma'),
    ];
    expect(searchMapObjects(objects, 'spectral finite -infinite').map((item) => item.id)).toEqual([
      'a',
    ]);
    expect(searchMapObjects(objects, '"spectral gaps" statement').map((item) => item.id)).toEqual([
      'a',
    ]);
    expect(searchMapObjects(objects, 'b-current').map((item) => item.id)).toEqual(['b']);
    expect(searchMapObjects(objects, 'cafe').map((item) => item.id)).toEqual(['c']);
    expect(searchMapObjects(objects, '"gaps spectral"')).toEqual([]);
  });
  it('loads every page, keeps isolated objects and pinned history, and deduplicates edges using public reads', async () => {
    const link = {
      id: 'link',
      source_object_version_id: 'a-old',
      target_object_version_id: 'b-current',
      relationship_type: 'USES',
    };
    const listObjects = vi.fn(async (_project, _public, cursor) =>
      cursor
        ? { items: [object('c', 'Isolated')] }
        : { items: [object('a', 'A'), object('b', 'B')], nextCursor: 'next' },
    );
    const listRelations = vi.fn(async (_project, id, _public, cursor) =>
      id === 'c'
        ? { items: [] }
        : cursor
          ? { items: [link] }
          : { items: [], nextCursor: 'relations-next' },
    );
    const listVersions = vi.fn(async (_project, id) => ({
      items: [{ id: `${id}-old`, content: { title: 'Historical' }, number: 1 }],
    }));
    const api = { listObjects, listRelations, listVersions } as unknown as ResearchApi;
    const result = await loadWorkspaceMap(api, 'workspace', true);
    expect(result.objects).toHaveLength(3);
    expect(result.nodes.find((node) => node.object_version_id === 'a-old')).toMatchObject({
      title: 'Historical',
      object_version_number: 1,
    });
    expect(result.nodes.find((node) => node.object_version_id === 'a-current')).toMatchObject({
      title: 'A',
      object_version_number: 2,
    });
    expect(result.relations).toEqual([link]);
    expect(result.nodes.map((node) => node.object_version_id)).toEqual(
      expect.arrayContaining(['a-current', 'b-current', 'c-current', 'a-old']),
    );
    expect(result.nodes.some((node) => node.object_version_id === 'b-old')).toBe(false);
    expect(listObjects).toHaveBeenCalledWith('workspace', true, 'next');
    expect(listRelations).toHaveBeenCalledWith('workspace', 'a', true, 'relations-next');
  });
  it('surfaces retrieval failures instead of presenting an incomplete map as complete', async () => {
    const api = {
      listObjects: async () => ({ items: [object('a', 'A')] }),
      listRelations: async () => {
        throw new Error('unavailable');
      },
    } as unknown as ResearchApi;
    await expect(loadWorkspaceMap(api, 'workspace')).rejects.toThrow('unavailable');
  });
});

it('keeps formalizations on their exact version instead of following a parent update', () => {
  const formalization = {
    ...object('formal', 'Formalization'),
    kind: 'FORMALIZATION',
  } as MapObject;
  formalization.current_object_version.structural_relationships = [];
  // An old object UUID association must never count as an exact formalization link.
  formalization.current_object_version.content.attached_object_ids = ['parent'];
  const data = {
    objects: [formalization],
    nodes: [],
    relations: [structuralPin('formal-current', 'parent-v1')],
  } as WorkspaceMap;
  expect(versionFormalizations(data, 'parent-v1').map((item) => item.id)).toEqual(['formal']);
  expect(versionFormalizations(data, 'parent-v2')).toEqual([]);
  expect(versionFormalizations(data, 'parent')).toEqual([]);
});

it('shows one node per object after a progress version while preserving original pins', () => {
  const objects = [object('proof', 'Proof'), object('statement', 'Statement')];
  const data: WorkspaceMap = {
    objects,
    nodes: [
      {
        object_id: 'proof',
        object_version_id: 'proof-old',
        title: 'Old proof',
        proof_direction: 'SUPPORTS',
      },
      {
        object_id: 'proof',
        object_version_id: 'proof-current',
        title: 'Proof',
        proof_direction: 'SUPPORTS',
      },
      { object_id: 'statement', object_version_id: 'statement-current', title: 'Statement' },
    ],
    relations: [
      structuralPin('proof-old', 'statement-current', 'CONCLUSION'),
      structuralPin('proof-current', 'statement-current', 'CONCLUSION'),
    ],
  };
  const diagram = objectDiagram(data);
  expect(diagram.nodes.map((node) => node.object_version_id)).toEqual([
    'proof-current',
    'statement-current',
  ]);
  expect(diagram.relations).toHaveLength(1);
  expect(diagram.relations[0]).toMatchObject({
    source_object_version_id: 'statement-current',
    target_object_version_id: 'proof-current',
  });
  expect(data.nodes).toHaveLength(3);
  expect(data.relations[0]).toMatchObject({ source_object_version_id: 'proof-old' });
});
