import { describe, expect, it } from 'vitest';
import { restoreProjectTabs, projectRouteTab } from '../../../src/web/src/lib/project-tabs';

describe('project route tabs', () => {
  it('uses stable route identities for pages and chats', () => {
    expect(projectRouteTab('project', '/projects/project')).toEqual({
      id: 'overview:',
      kind: 'page',
      label: 'Overview',
      href: '/projects/project',
    });
    expect(projectRouteTab('project', '/projects/project/conversations/saved')).toEqual({
      id: 'conversations:saved',
      kind: 'chat',
      label: 'Chat',
      href: '/projects/project/conversations/saved',
    });
    expect(projectRouteTab('project', '/projects/project/conversations/chat')).toEqual({
      id: 'conversations:chat',
      kind: 'chat',
      label: 'Chat',
      href: '/projects/project/conversations/chat',
    });
    expect(projectRouteTab('project', '/projects/project/conversations/new')?.label).toBe(
      'New chat',
    );
    expect(projectRouteTab('project', '/projects/project/conversations')?.kind).toBe('page');
  });

  it('preserves query parameters without changing identity', () => {
    const first = projectRouteTab(
      'project',
      '/projects/project/conversations?kind=THEOREM&q=a%20b',
    );
    const second = projectRouteTab('project', '/projects/project/conversations?kind=PROOF');
    expect(first?.href).toBe('/projects/project/conversations?kind=THEOREM&q=a%20b');
    expect(first?.id).toBe(second?.id);
  });

  it('keeps new chat drafts distinct while existing sessions retain their identity', () => {
    const first = projectRouteTab('project', '/projects/project/conversations/new?draft=first');
    const second = projectRouteTab('project', '/projects/project/conversations/new?draft=second');
    expect(first?.id).toBe('conversations:new:first');
    expect(second?.id).toBe('conversations:new:second');
    expect(projectRouteTab('project', '/projects/project/conversations/new')?.id).toBe(
      'conversations:new',
    );
    expect(projectRouteTab('project', '/projects/project/conversations/chat?draft=first')?.id).toBe(
      'conversations:chat',
    );
    expect(restoreProjectTabs('project', JSON.stringify([first, second, first]))).toEqual([
      first,
      second,
    ]);
  });

  it('rejects routes outside the current project and unknown sections', () => {
    for (const href of [
      '/projects/other/conversations',
      '/projects/other/conversations/chat',
      '/conversations',
      '/projects/project/unknown',
      '/projects/project/chat',
      'https://example.com/projects/project/conversations',
      '//example.com/projects/project/conversations',
      '/projects/project/overview/anything',
      '/projects/project/conversations/chat/extra',
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
          href: '/projects/project/overview?q=first',
          label: 'Untrusted',
          kind: 'chat',
          dirty: true,
        },
        { href: '/projects/project/overview?q=duplicate' },
        { href: '/projects/other/conversations' },
        { href: 'https://example.com/projects/project/conversations' },
        { href: '/projects/project/unknown' },
        { href: '/projects/project/chat' },
        { href: '/projects/project/overview/anything' },
        { href: '/projects/project/conversations/chat/extra' },
        { href: 'http://[' },
        { href: '/projects/project/files' },
        { href: '/projects/project/conversations/saved?revision=2' },
        null,
        {},
        { href: 1 },
      ]),
    );
    expect(restored).toEqual([
      {
        id: 'conversations:saved',
        kind: 'chat',
        label: 'Chat',
        href: '/projects/project/conversations/saved?revision=2',
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
        href: `/projects/project/conversations/saved-${index}`,
      })),
    );
    expect(restoreProjectTabs('project', raw)).toHaveLength(30);
  });
});

it('does not restore tabs from retired workspace routes', () => {
  expect(
    restoreProjectTabs(
      'project',
      JSON.stringify([
        { href: '/workspaces/project/conversations/saved?revision=old#proof' },
        { href: '/projects/project/sessions/saved' },
      ]),
    ),
  ).toEqual([]);
});
