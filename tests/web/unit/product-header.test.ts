import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';

import ProductHeader from '../../../src/web/src/ui/ProductHeader.svelte';
import { Auth } from '../../../src/web/src/svelte-lib/auth.svelte';

afterEach(cleanup);

function signedInAuth() {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: true, username: 'ada', display_name: 'Ada Lovelace' };
  auth.loaded = true;
  return auth;
}

function signedOutAuth() {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: false };
  auth.loaded = true;
  return auth;
}

it('keeps unresolved authentication neutral in desktop and mobile account controls', async () => {
  const auth = new Auth(() => {});
  render(ProductHeader, { props: { auth, active: 'explore' } });

  expect(screen.getByRole('status', { name: 'Checking account' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Sign in' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Create account' })).toBeNull();
  expect(screen.queryByRole('button', { name: /Open account menu/ })).toBeNull();

  await fireEvent.click(screen.getByRole('button', { name: 'Open navigation and account menu' }));
  expect(await screen.findByText('Checking account…')).toBeTruthy();
  expect(screen.queryByRole('menuitem', { name: 'Sign in' })).toBeNull();
  expect(screen.queryByRole('menuitem', { name: 'Create account' })).toBeNull();
});

it('uses clear global destinations and exposes account destinations from the avatar menu', async () => {
  render(ProductHeader, { props: { auth: signedInAuth(), active: 'projects' } });

  const brand = screen.getByRole('link', { name: 'Polycolab home' });
  expect(brand.querySelector('img')?.getAttribute('src')).toBe('/brand/polycolab-mark.png');
  const navigation = screen.getByRole('navigation', { name: 'Main navigation' });
  expect(within(navigation).getByRole('link', { name: 'Library' }).getAttribute('href')).toBe(
    '/library',
  );
  expect(within(navigation).getByRole('link', { name: 'Docs' }).getAttribute('href')).toBe(
    '/docs/',
  );
  expect(within(navigation).getByRole('button', { name: 'Open Docs menu' })).toBeTruthy();
  expect(
    within(navigation)
      .getAllByRole('link')
      .map((link) => link.textContent?.trim()),
  ).toEqual(['Library', 'Projects', 'Activity', 'Chat Planned', 'Docs']);
  expect(
    within(navigation)
      .getByRole('link', { name: /^Activity/ })
      .getAttribute('href'),
  ).toBe('/activity');
  expect(
    within(navigation).getByRole('link', { name: 'Projects' }).getAttribute('aria-current'),
  ).toBe('page');
  expect(within(navigation).queryByRole('link', { name: 'Settings' })).toBeNull();

  await fireEvent.click(screen.getByRole('button', { name: 'Open account menu for Ada Lovelace' }));
  for (const item of [
    'Profile',
    'Your projects',
    'Settings',
    'Password and authentication',
    'Getting started',
    'Moderation',
  ])
    expect(await screen.findByRole('menuitem', { name: item })).toBeTruthy();
  expect(screen.getByText('@ada')).toBeTruthy();
  expect(screen.queryByRole('menuitem', { name: 'Your activities' })).toBeNull();
  expect(screen.queryByRole('menuitem', { name: 'Agent connections' })).toBeNull();
  expect(screen.queryByRole('menuitem', { name: 'API keys' })).toBeNull();
  expect(screen.queryByRole('menuitem', { name: 'Administration' })).toBeNull();
  expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeTruthy();
  expect(screen.getAllByText('AL', { exact: true })).toHaveLength(2);
  expect(
    screen.getByRole('button', { name: 'Open account menu for Ada Lovelace' }).textContent,
  ).toContain('AL');
});

it('keeps the project breadcrumb focused on its name and directory link', () => {
  render(ProductHeader, {
    props: {
      auth: signedInAuth(),
      active: 'projects',
      projectName: 'Spectral gaps',
      projectVisibility: 'PRIVATE',
    },
  });

  const breadcrumb = screen.getByRole('navigation', { name: 'Project breadcrumb' });
  expect(within(breadcrumb).getByRole('link', { name: 'Projects' }).getAttribute('href')).toBe(
    '/projects',
  );
  expect(within(breadcrumb).getByText('Spectral gaps', { exact: true })).toBeTruthy();
  expect(screen.queryByRole('navigation', { name: 'Main navigation' })).toBeNull();
});

it('links anonymous desktop and mobile navigation to public projects', async () => {
  render(ProductHeader, { props: { auth: signedOutAuth(), active: 'explore' } });

  const navigation = screen.getByRole('navigation', { name: 'Main navigation' });
  expect(
    within(navigation).getByRole('link', { name: 'Library' }).getAttribute('aria-current'),
  ).toBe('page');
  expect(within(navigation).getByRole('link', { name: 'Library' }).getAttribute('href')).toBe(
    '/library',
  );
  expect(within(navigation).getByRole('button', { name: 'Open Docs menu' })).toBeTruthy();
  expect(within(navigation).getByRole('link', { name: 'Projects' }).getAttribute('href')).toBe(
    '/projects?scope=public',
  );
  expect(
    within(navigation)
      .getByRole('link', { name: /^Activity/ })
      .getAttribute('href'),
  ).toBe('/activity');
  expect(screen.getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/signin');
  expect(screen.getByRole('link', { name: 'Create account' }).getAttribute('href')).toBe('/signup');

  await fireEvent.click(screen.getByRole('button', { name: 'Open navigation and account menu' }));
  expect((await screen.findByRole('menuitem', { name: 'Projects' })).getAttribute('href')).toBe(
    '/projects?scope=public',
  );
  expect(screen.getByRole('menuitem', { name: 'Docs' }).getAttribute('href')).toBe('/docs/');
  expect(screen.getByRole('menuitem', { name: 'Getting started' }).getAttribute('href')).toBe(
    '/docs/getting-started/',
  );
  expect(screen.getByRole('menuitem', { name: 'Developers' }).getAttribute('href')).toBe(
    '/docs/developers/',
  );
});

it('marks Docs as the current public destination', () => {
  render(ProductHeader, { props: { auth: signedOutAuth(), active: 'docs' } });

  const navigation = screen.getByRole('navigation', { name: 'Main navigation' });
  expect(within(navigation).getByRole('link', { name: 'Docs' }).getAttribute('aria-current')).toBe(
    'page',
  );
});

it('keeps the account available after sign-out fails', async () => {
  const auth = signedInAuth();
  vi.spyOn(auth, 'signOut').mockRejectedValueOnce(new Error('offline'));
  render(ProductHeader, { props: { auth, active: 'projects' } });

  await fireEvent.click(screen.getByRole('button', { name: 'Open account menu for Ada Lovelace' }));
  await fireEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Sign-out failed. Please retry.');
  expect(screen.getByRole('button', { name: 'Open account menu for Ada Lovelace' })).toBeTruthy();
});

it('marks Activity as current for anonymous desktop and mobile navigation', async () => {
  render(ProductHeader, { props: { auth: signedOutAuth(), active: 'activity' } });
  const navigation = screen.getByRole('navigation', { name: 'Main navigation' });
  expect(
    within(navigation)
      .getByRole('link', { name: /^Activity/ })
      .getAttribute('aria-current'),
  ).toBe('page');
  expect(within(navigation).queryByRole('link', { name: /Commons/ })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Open navigation and account menu' }));
  const activity = await screen.findByRole('menuitem', { name: /^Activity/ });
  expect(activity.textContent).not.toContain('Planned');
  expect(screen.getByRole('menuitem', { name: /Chat.*Planned/ }).getAttribute('href')).toBe(
    '/chat',
  );
  expect(activity.getAttribute('href')).toBe('/activity');
  expect(activity.getAttribute('aria-current')).toBe('page');
});

it('links the Docs label and exposes the main documentation routes', async () => {
  render(ProductHeader, { props: { auth: signedOutAuth(), active: 'docs' } });
  const nav = screen.getByRole('navigation', { name: 'Main navigation' });
  expect(within(nav).queryByRole('link', { name: 'Search' })).toBeNull();
  expect(within(nav).getByRole('link', { name: 'Docs' }).getAttribute('href')).toBe('/docs/');
  await fireEvent.click(within(nav).getByRole('button', { name: 'Open Docs menu' }));
  expect(
    (await screen.findByRole('menuitem', { name: 'Getting started' })).getAttribute('href'),
  ).toBe('/docs/getting-started/');
  expect(screen.getByRole('menuitem', { name: 'Developers' }).getAttribute('href')).toBe(
    '/docs/developers/',
  );
});
