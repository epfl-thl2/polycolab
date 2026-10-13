import type { Page } from '@playwright/test';

export const adaId = '11111111-1111-4111-8111-111111111111';
export const noorId = '22222222-2222-4222-8222-222222222222';
export const revisionId = '33333333-3333-4333-8333-333333333333';

export async function mockProfiles(page: Page, signedIn = false) {
  const state = { signedIn, username: 'ada', identityUnavailable: false };
  const researchers = [
    {
      actor: { kind: 'human', username: 'ada', display_name: 'Ada' },
      authored_contributions: 2,
      sponsored_contributions: 1,
    },
    {
      actor: { kind: 'human', username: 'noor', display_name: 'Noor' },
      authored_contributions: 1,
      sponsored_contributions: 0,
    },
  ];
  await page.route('**/auth/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/auth/config')
      return route.fulfill({ json: { mode: 'local', registration_mode: 'closed' } });
    if (path === '/auth/login') {
      state.signedIn = true;
      state.username = route.request().postDataJSON().username;
    }
    if (path === '/auth/logout') state.signedIn = false;
    return route.fulfill({
      json: {
        authenticated: state.signedIn,
        username: state.username,
        display_name: state.username === 'ada' ? 'Ada' : 'Noor',
      },
    });
  });
  await page.route('**/api/v1/users/me', (route) =>
    state.identityUnavailable
      ? route.fulfill({ status: 503, json: { error: { code: 'temporarily_unavailable' } } })
      : route.fulfill({
          json: {
            id: state.username === 'ada' ? adaId : noorId,
            username: state.username,
            display_name: state.username,
            email: null,
          },
        }),
  );
  await page.route('**/api/v1/profile/**', (route) => {
    const url = new URL(route.request().url());
    const person = researchers.find(
      (person) => person.actor.username === url.pathname.split('/')[4],
    );
    if (!person) return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
    if (url.pathname.endsWith('/activity'))
      return route.fulfill({
        json: {
          items: [
            {
              id: `${person.actor.username}-event`,
              submission_number: 1,
              contribution_id: null,
              action: 'object.created',
              actor: person.actor,
              object_id: '44444444-4444-4444-8444-444444444444',
              object_version_id: revisionId,
              previous_object_version_id: null,
              object_kind: 'PROOF',
              title: `${person.actor.display_name}'s public proof`,
              excerpt_md: 'Public work only.',
              project_id: null,
              occurred_at: '2026-10-12T10:00:00Z',
              reconstructed: false,
            },
          ],
          next_cursor: null,
        },
      });
    return route.fulfill({ json: person });
  });
  return state;
}
