import { expect, it } from 'vitest';
import { canonicalUiLocation } from '../../../src/web/src/lib/ui-location';
it('preserves workspace bookmarks and file query strings', () => {
  expect(canonicalUiLocation('/workspaces/id', '?path=notes.md')).toBe(
    '/projects/id?path=notes.md',
  );
  expect(canonicalUiLocation('/projects/id/chat', '?draft=a')).toBe(
    '/projects/id/sessions?draft=a',
  );
});
it('keeps retired routes unavailable rather than aliasing them into projects', () => {
  for (const path of ['/library', '/commons', '/activity', '/profile', '/search'])
    expect(canonicalUiLocation(path, '')).toBe(path);
});

it('redirects saved identity Connections links to key settings', () => {
  expect(canonicalUiLocation('/agents/connections', '?from=bookmark')).toBe(
    '/settings/api-keys?from=bookmark',
  );
});
