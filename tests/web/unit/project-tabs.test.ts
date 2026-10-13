import { describe, expect, it } from 'vitest';
import { restoreProjectTabs, projectRouteTab } from '../../../src/web/src/lib/project-tabs';

describe('project route tabs', () => {
  it('uses stable route identities for pages, objects and chats', () => {
    expect(projectRouteTab('project', '/projects/project')).toEqual({
      id: 'overview:',
      kind: 'page',
      label: 'Overview',
      href: '/projects/project',
    });
    expect(projectRouteTab('project', '/projects/project/objects/object')).toEqual({
      id: 'objects:object',
      kind: 'object',
      label: 'Research object',
      href: '/projects/project/objects/object',
    });
    expect(projectRouteTab('project', '/projects/project/sessions/chat')).toEqual({
      id: 'sessions:chat',
      kind: 'chat',
      label: 'Chat',
      href: '/projects/project/sessions/chat',
    });
    expect(projectRouteTab('project', '/projects/project/sessions/new')?.label).toBe('New chat');
    expect(projectRouteTab('project', '/projects/project/sessions')?.kind).toBe('page');
  });

  it('preserves query parameters without changing identity', () => {
    const first = projectRouteTab('project', '/projects/project/research?kind=THEOREM&q=a%20b');
    const second = projectRouteTab('project', '/projects/project/research?kind=PROOF');
    expect(first?.href).toBe('/projects/project/research?kind=THEOREM&q=a%20b');
    expect(first?.id).toBe(second?.id);
  });

  it('keeps new chat drafts distinct while existing sessions retain their identity', () => {
    const first = projectRouteTab('project', '/projects/project/sessions/new?draft=first');
    const second = projectRouteTab('project', '/projects/project/sessions/new?draft=second');
    expect(first?.id).toBe('sessions:new:first');
    expect(second?.id).toBe('sessions:new:second');
    expect(projectRouteTab('project', '/projects/project/sessions/new')?.id).toBe('sessions:new');
    expect(projectRouteTab('project', '/projects/project/sessions/chat?draft=first')?.id).toBe(
      'sessions:chat',
    );
    expect(restoreProjectTabs('project', JSON.stringify([first, second, first]))).toEqual([
      first,
      second,
    ]);
  });

  it('rejects routes outside the current project and unknown sections', () => {
    for (const href of [
      '/projects/other/research',
      '/projects/other/sessions/chat',
      '/research',
      '/projects/project/unknown',
      'https://example.com/projects/project/research',
      '//example.com/projects/project/research',
      '/projects/project/overview/anything',
      '/projects/project/sessions/chat/extra',
      '/projects/project/objects',
      'http://[',
    ])
      expect(projectRouteTab('project', href)).toBeUndefined();
  });
});

describe('restored project tabs', () => {
  it('reconstructs trusted metadata, keeps queries, and rejects duplicate, foreign and invalid routes', () => {
    const restored = restoreProjectTabs(
      'project',
      JSON.stringify([
        {
          href: '/projects/project/research?q=first',
          label: 'Untrusted',
          kind: 'chat',
          dirty: true,
        },
        { href: '/projects/project/research?q=duplicate' },
        { href: '/projects/other/research' },
        { href: 'https://example.com/projects/project/research' },
        { href: '/projects/project/unknown' },
        { href: '/projects/project/overview/anything' },
        { href: '/projects/project/sessions/chat/extra' },
        { href: 'http://[' },
        { href: '/projects/project/files' },
        { href: '/projects/project/objects/object?revision=2' },
        null,
        {},
        { href: 1 },
      ]),
    );
    expect(restored).toEqual([
      {
        id: 'objects:object',
        kind: 'object',
        label: 'Research object',
        href: '/projects/project/objects/object?revision=2',
      },
    ]);
  });

  it('returns no tabs for missing, malformed or non-array storage', () => {
    for (const raw of [null, '{', 'null', '{}', '"string"', '123'])
      expect(restoreProjectTabs('project', raw)).toEqual([]);
  });

  it('bounds restored entries to thirty', () => {
    const raw = JSON.stringify(
      Array.from({ length: 35 }, (_, index) => ({
        href: `/projects/project/objects/object-${index}`,
      })),
    );
    expect(restoreProjectTabs('project', raw)).toHaveLength(30);
  });
});

it('restores old bookmarks as project tabs without changing identity or query and fragment', () => {
  expect(
    restoreProjectTabs(
      'project',
      JSON.stringify([{ href: '/workspaces/project/objects/object?revision=old#proof' }]),
    ),
  ).toEqual([
    {
      id: 'objects:object',
      kind: 'object',
      label: 'Research object',
      href: '/projects/project/objects/object?revision=old#proof',
    },
  ]);
});
