import { expect, it } from 'vitest';
import { canonicalUiLocation } from '../../../src/web/src/lib/ui-location';

it('preserves canonical paths and query strings without legacy redirects', () => {
  for (const path of [
    '/projects/id/conversations/new',
    '/settings/provider-connections',
    '/workspaces/id',
    '/projects/id/sessions',
    '/projects/id/chat',
    '/agents/connections',
    '/settings/providers',
    '/settings/model-providers',
    '/settings/agent-keys',
    '/settings/session-history',
  ])
    expect(canonicalUiLocation(path, '?source=bookmark')).toBe(path + '?source=bookmark');
});
