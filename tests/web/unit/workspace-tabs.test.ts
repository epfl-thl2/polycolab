import { describe, expect, it } from 'vitest';
import { restoreWorkspaceTabs, workspaceRouteTab } from '../../../web/src/lib/workspace-tabs';

describe('workspace route tabs', () => {
  it('uses stable route identities for pages, objects and chats', () => {
    expect(workspaceRouteTab('workspace', '/workspaces/workspace')).toEqual({
      id: 'overview:',
      kind: 'page',
      label: 'Overview',
      href: '/workspaces/workspace',
    });
    expect(workspaceRouteTab('workspace', '/projects/workspace/objects/object')).toEqual({
      id: 'objects:object',
      kind: 'object',
      label: 'Research object',
      href: '/projects/workspace/objects/object',
    });
    expect(workspaceRouteTab('workspace', '/workspaces/workspace/sessions/chat')).toEqual({
      id: 'sessions:chat',
      kind: 'chat',
      label: 'Chat',
      href: '/workspaces/workspace/sessions/chat',
    });
    expect(workspaceRouteTab('workspace', '/workspaces/workspace/sessions/new')?.label).toBe(
      'New chat',
    );
    expect(workspaceRouteTab('workspace', '/workspaces/workspace/sessions')?.kind).toBe('page');
  });

  it('preserves query parameters without changing identity', () => {
    const first = workspaceRouteTab(
      'workspace',
      '/workspaces/workspace/research?kind=THEOREM&q=a%20b',
    );
    const second = workspaceRouteTab('workspace', '/workspaces/workspace/research?kind=PROOF');
    expect(first?.href).toBe('/workspaces/workspace/research?kind=THEOREM&q=a%20b');
    expect(first?.id).toBe(second?.id);
  });

  it('keeps new chat drafts distinct while existing sessions retain their identity', () => {
    const first = workspaceRouteTab('workspace', '/workspaces/workspace/sessions/new?draft=first');
    const second = workspaceRouteTab(
      'workspace',
      '/workspaces/workspace/sessions/new?draft=second',
    );
    expect(first?.id).toBe('sessions:new:first');
    expect(second?.id).toBe('sessions:new:second');
    expect(workspaceRouteTab('workspace', '/workspaces/workspace/sessions/new')?.id).toBe(
      'sessions:new',
    );
    expect(
      workspaceRouteTab('workspace', '/workspaces/workspace/sessions/chat?draft=first')?.id,
    ).toBe('sessions:chat');
    expect(restoreWorkspaceTabs('workspace', JSON.stringify([first, second, first]))).toEqual([
      first,
      second,
    ]);
  });

  it('rejects routes outside the current workspace and unknown sections', () => {
    for (const href of [
      '/workspaces/other/research',
      '/projects/other/sessions/chat',
      '/research',
      '/workspaces/workspace/unknown',
      'https://example.com/workspaces/workspace/research',
      '//example.com/workspaces/workspace/research',
      '/workspaces/workspace/overview/anything',
      '/workspaces/workspace/sessions/chat/extra',
      '/workspaces/workspace/objects',
      'http://[',
    ])
      expect(workspaceRouteTab('workspace', href)).toBeUndefined();
  });
});

describe('restored workspace tabs', () => {
  it('reconstructs trusted metadata, keeps queries, and rejects duplicate, foreign and invalid routes', () => {
    const restored = restoreWorkspaceTabs(
      'workspace',
      JSON.stringify([
        {
          href: '/workspaces/workspace/research?q=first',
          label: 'Untrusted',
          kind: 'chat',
          dirty: true,
        },
        { href: '/projects/workspace/research?q=duplicate' },
        { href: '/workspaces/other/research' },
        { href: 'https://example.com/workspaces/workspace/research' },
        { href: '/workspaces/workspace/unknown' },
        { href: '/workspaces/workspace/overview/anything' },
        { href: '/workspaces/workspace/sessions/chat/extra' },
        { href: 'http://[' },
        { href: '/workspaces/workspace/files' },
        { href: '/workspaces/workspace/objects/object?revision=2' },
        null,
        {},
        { href: 1 },
      ]),
    );
    expect(restored).toEqual([
      {
        id: 'research:',
        kind: 'page',
        label: 'Research objects',
        href: '/workspaces/workspace/research?q=first',
      },
      {
        id: 'objects:object',
        kind: 'object',
        label: 'Research object',
        href: '/workspaces/workspace/objects/object?revision=2',
      },
    ]);
  });

  it('returns no tabs for missing, malformed or non-array storage', () => {
    for (const raw of [null, '{', 'null', '{}', '"string"', '123'])
      expect(restoreWorkspaceTabs('workspace', raw)).toEqual([]);
  });

  it('bounds restored entries to thirty', () => {
    const raw = JSON.stringify(
      Array.from({ length: 35 }, (_, index) => ({
        href: `/workspaces/workspace/objects/object-${index}`,
      })),
    );
    expect(restoreWorkspaceTabs('workspace', raw)).toHaveLength(30);
  });
});
