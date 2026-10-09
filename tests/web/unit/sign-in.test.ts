import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

import SignIn from '../../../src/web/src/ui/SignIn.svelte';
import { Auth } from '../../../src/web/src/svelte-lib/auth.svelte';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function localAuth(
  registrationMode?: 'open' | 'invitation' | 'closed',
  externalProviders?: Array<'google' | 'github'>,
) {
  const auth = new Auth(() => {});
  auth.configuration = {
    mode: 'local',
    registration_mode: registrationMode,
    social_providers: externalProviders,
  };
  auth.account = { authenticated: false };
  auth.loaded = true;
  return auth;
}

it('links sign in to the account creation route', () => {
  render(SignIn, { props: { auth: localAuth() } });

  expect(screen.getByRole('heading', { name: 'Sign in' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Sign up' }).getAttribute('href')).toBe('/signup');
});

it('shows configured social providers for built-in sign in', () => {
  render(SignIn, { props: { auth: localAuth('open', ['google', 'github']) } });

  expect(screen.getByRole('button', { name: 'Google' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'GitHub' })).toBeTruthy();
  expect(screen.getByRole('group', { name: 'Social sign-in' })).toBeTruthy();
  expect(screen.getByText('or continue with')).toBeTruthy();
  expect(screen.getByLabelText('Username')).toBeTruthy();
  expect(screen.getByLabelText('Password')).toBeTruthy();
});

it('links unavailable social providers to the not-found page', () => {
  render(SignIn, { props: { auth: localAuth('open', ['google']) } });

  expect(screen.getByRole('button', { name: 'Google' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'GitHub' }).getAttribute('href')).toBe('/404');
});

it('shows both social alternatives when neither provider is configured', () => {
  render(SignIn, { props: { auth: localAuth() } });

  for (const provider of ['Google', 'GitHub']) {
    expect(screen.getByRole('link', { name: provider }).getAttribute('href')).toBe('/404');
  }
});

it('explains the invitation boundary for an established local deployment', () => {
  render(SignIn, { props: { auth: localAuth(), mode: 'signup' } });

  expect(
    screen.getByRole('heading', { name: 'Account creation is managed by this deployment' }),
  ).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Return to sign in' }).getAttribute('href')).toBe(
    '/signin',
  );
});

it('keeps social account creation hidden when built-in registration is managed', () => {
  render(SignIn, {
    props: { auth: localAuth('closed', ['google', 'github']), mode: 'signup' },
  });

  expect(screen.queryByRole('link', { name: 'Google' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'GitHub' })).toBeNull();
  expect(screen.getByText(/Ask the Polycolab administrator/)).toBeTruthy();
});

it('renders and submits the configured open-registration form', async () => {
  const auth = localAuth('open');
  vi.spyOn(auth, 'initialize').mockResolvedValue(undefined);
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ authenticated: true }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetch);
  render(SignIn, { props: { auth, mode: 'signup' } });

  await fireEvent.input(screen.getByLabelText('Display name'), { target: { value: 'Ada' } });
  await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'ada' } });
  await fireEvent.input(screen.getByLabelText('Password'), {
    target: { value: 'correct-horse-battery-staple' },
  });
  await fireEvent.input(screen.getByLabelText('Confirm password'), {
    target: { value: 'correct-horse-battery-staple' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/auth/register',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          username: 'ada',
          password: 'correct-horse-battery-staple',
          display_name: 'Ada',
        }),
      }),
    ),
  );
});

it('requires an invitation code when registration is invitation-only', () => {
  render(SignIn, { props: { auth: localAuth('invitation'), mode: 'signup' } });

  expect(screen.getByLabelText('Invitation code')).toBeTruthy();
  expect(screen.queryByLabelText('Email')).toBeNull();
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.getByLabelText('Confirm password')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/signin');
});

it('shows the sanitized registration error returned by the service', async () => {
  const auth = localAuth('invitation');
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        error: { code: 'invalid_registration_invitation', request_id: 'request-a' },
      }),
      { status: 400, headers: { 'Content-Type': 'application/json' } },
    ),
  );
  vi.stubGlobal('fetch', fetch);
  render(SignIn, { props: { auth, mode: 'signup' } });

  await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'ada' } });
  await fireEvent.input(screen.getByLabelText('Invitation code'), {
    target: { value: 'x'.repeat(32) },
  });
  await fireEvent.input(screen.getByLabelText('Password'), {
    target: { value: 'correct-horse-battery-staple' },
  });
  await fireEvent.input(screen.getByLabelText('Confirm password'), {
    target: { value: 'correct-horse-battery-staple' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect((await screen.findByRole('alert')).textContent).toBe(
    'That invitation code is invalid or expired.',
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss error' }));
  expect(screen.queryByRole('alert')).toBeNull();
});

it('starts OIDC registration from the create-account screen', async () => {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'oidc' };
  auth.loaded = true;
  const signUp = vi.spyOn(auth, 'signUp').mockResolvedValue(undefined);
  render(SignIn, { props: { auth, mode: 'signup' } });

  await fireEvent.click(screen.getByRole('button', { name: 'Continue to create account' }));

  expect(signUp).toHaveBeenCalledOnce();
});

it('toggles password visibility without submitting or clearing the input', async () => {
  const auth = localAuth();
  const initialize = vi.spyOn(auth, 'initialize');
  render(SignIn, { props: { auth } });
  const input = screen.getByLabelText('Password') as HTMLInputElement;
  await fireEvent.input(input, { target: { value: 'a-test-password' } });
  expect(input.type).toBe('password');
  const toggle = screen.getByRole('button', { name: 'Show password' });
  expect(toggle.getAttribute('type')).toBe('button');
  await fireEvent.click(toggle);
  expect(input.type).toBe('text');
  expect(input.value).toBe('a-test-password');
  await fireEvent.click(screen.getByRole('button', { name: 'Hide password' }));
  expect(input.type).toBe('password');
  expect(input.value).toBe('a-test-password');
  expect(initialize).not.toHaveBeenCalled();
});

it('shows provider failures as dismissible toasts', async () => {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'oidc' };
  auth.loaded = true;
  vi.spyOn(auth, 'signIn').mockRejectedValue(new Error('Could not connect.'));
  render(SignIn, { props: { auth } });
  await fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect((await screen.findByRole('alert')).textContent).toBe('Could not connect.');
  await fireEvent.click(screen.getByRole('button', { name: 'Dismiss error' }));
  expect(screen.queryByRole('alert')).toBeNull();
});
