import { expect, it } from 'vitest';
import { accountHref, accountReturnPath } from '../../../src/web/src/lib/account-navigation';

it.each([
  undefined,
  '//external.example',
  'https://external.example',
  '/\\external.example',
  '/x/..//external.example',
  '/signin?returnTo=/signin',
  '/signup',
  '/auth/logout',
  '/oidc/callback',
  '/%73ignin',
  '/\n/external.example',
])('uses projects for an unsafe or looping destination: %s', (value) => {
  expect(accountReturnPath(value)).toBe('/projects');
});

it('preserves local query and fragment through both account entry points', () => {
  const path = '/projects/research?q=spectral#history';
  expect(accountReturnPath(path)).toBe(path);
  for (const mode of ['signin', 'signup'] as const) {
    const url = new URL(accountHref(mode, path), 'https://polycolab.example');
    expect(url.pathname).toBe(`/${mode}`);
    expect(url.searchParams.get('returnTo')).toBe(path);
  }
  expect(accountHref('signin')).toBe('/signin');
});
