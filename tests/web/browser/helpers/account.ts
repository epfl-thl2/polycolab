import type { Page } from '@playwright/test';

export const adaId = '11111111-1111-4111-8111-111111111111';
export const noorId = '22222222-2222-4222-8222-222222222222';

export async function mockAccount(page: Page, signedIn = false) {
  const state = { signedIn, username: 'ada', identityUnavailable: false };
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
  await page.route('**/api/v1/projects?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null, total: 0 } }),
  );
  return state;
}
