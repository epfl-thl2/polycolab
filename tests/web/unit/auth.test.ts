import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  Auth,
  authConfigurationCacheKey,
  externalAuthStartUrl,
  readCachedAuthConfiguration,
  safeReturnPath,
} from '../../../src/web/src/svelte-lib/auth.svelte';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  sessionStorage.clear();
});

it('does not start silent OIDC sign-in for an anonymous shared API read', async () => {
  const signinSilent = vi.fn();
  const auth = new Auth(() => {});
  auth.manager = {
    getUser: vi.fn().mockResolvedValue(null),
    signinSilent,
  } as unknown as NonNullable<Auth['manager']>;
  expect(await auth.token()).toBeUndefined();
  expect(signinSilent).not.toHaveBeenCalled();
  expect(auth.error).toBe('');
});

describe('authentication configuration cache', () => {
  it('skips the configuration request on a warm reload but still validates the local session', async () => {
    const paths: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'https://polycolab.example').pathname;
        paths.push(path);
        return new Response(
          JSON.stringify(
            path === '/auth/config'
              ? {
                  mode: 'local',
                  social_providers: ['google'],
                  external_providers: ['github'],
                  client_secret: 'must-not-be-cached',
                }
              : { authenticated: true, username: 'ada', display_name: 'Ada' },
          ),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );

    await new Auth(() => {}).initialize();
    await new Auth(() => {}).initialize();

    expect(paths).toEqual(['/auth/config', '/auth/me', '/auth/me']);
    expect(sessionStorage.getItem(authConfigurationCacheKey)).not.toContain('ada');
    expect(sessionStorage.getItem(authConfigurationCacheKey)).not.toContain('client_secret');
    expect(sessionStorage.getItem(authConfigurationCacheKey)).not.toContain('external_providers');
    expect(readCachedAuthConfiguration()?.social_providers).toEqual(['google']);
  });

  it.each([
    ['malformed JSON', '{'],
    [
      'expired data',
      JSON.stringify({ expires_at: Date.now() - 1, configuration: { mode: 'local' } }),
    ],
    [
      'invalid configuration',
      JSON.stringify({ expires_at: Date.now() + 60_000, configuration: { mode: 'unknown' } }),
    ],
  ])('discards %s', async (_, cached) => {
    sessionStorage.setItem(authConfigurationCacheKey, cached);
    expect(readCachedAuthConfiguration()).toBeUndefined();
    expect(sessionStorage.getItem(authConfigurationCacheKey)).toBeNull();
  });

  it('accepts complete browser-safe OIDC configuration without caching a user', () => {
    const configuration = {
      mode: 'oidc',
      issuer: 'https://identity.example',
      client_id: 'polycolab-web',
      audience: 'polycolab-api',
    };
    sessionStorage.setItem(
      authConfigurationCacheKey,
      JSON.stringify({ expires_at: Date.now() + 60_000, configuration }),
    );

    expect(readCachedAuthConfiguration()).toEqual(configuration);
  });

  it('treats unavailable browser storage as a cache miss', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new DOMException('blocked');
      },
    });
    expect(readCachedAuthConfiguration()).toBeUndefined();
  });

  it('evicts failed cached configuration and retries once from the service', async () => {
    sessionStorage.setItem(
      authConfigurationCacheKey,
      JSON.stringify({
        expires_at: Date.now() + 60_000,
        configuration: { mode: 'local' },
      }),
    );
    const paths: string[] = [];
    let meAttempts = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'https://polycolab.example').pathname;
        paths.push(path);
        if (path === '/auth/me' && meAttempts++ === 0) return new Response(null, { status: 404 });
        return new Response(
          JSON.stringify(
            path === '/auth/config' ? { mode: 'local' } : { authenticated: true, username: 'ada' },
          ),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    const auth = new Auth(() => {});

    await auth.initialize();

    expect(paths).toEqual(['/auth/me', '/auth/config', '/auth/me']);
    expect(auth.signedIn).toBe(true);
    expect(auth.error).toBe('');
  });
});

describe('OIDC return paths', () => {
  it('retains the requested page for provider sign-in and registration', async () => {
    const signinRedirect = vi.fn().mockResolvedValue(undefined);
    const auth = new Auth(() => {});
    auth.manager = { signinRedirect } as unknown as NonNullable<typeof auth.manager>;
    const returnTo = '/library/new';
    await auth.signIn(returnTo);
    expect(signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo } });
    await auth.signUp(returnTo);
    expect(signinRedirect).toHaveBeenLastCalledWith({
      state: { returnTo },
      extraQueryParams: { screen_hint: 'signup' },
    });
  });
  it.each([
    ['/projects/project-a?tab=history#latest', '/projects/project-a?tab=history#latest'],
    ['/', '/'],
    ['https://attacker.example/path', '/'],
    ['//attacker.example/path', '/'],
    ['/\\attacker.example/path', '/'],
    ['\\\\attacker.example/path', '/'],
    ['projects/project-a', '/'],
    [undefined, '/'],
  ])('normalizes %s to a same-origin return path', (value, expected) => {
    expect(safeReturnPath(value, 'https://polycolab.example')).toBe(expected);
  });

  it('requests the identity provider signup screen and returns to workspaces', async () => {
    const signinRedirect = vi.fn().mockResolvedValue(undefined);
    const auth = new Auth(() => {});
    auth.manager = { signinRedirect } as unknown as NonNullable<typeof auth.manager>;

    await auth.signUp();

    expect(signinRedirect).toHaveBeenCalledWith({
      state: { returnTo: '/workspaces' },
      extraQueryParams: { screen_hint: 'signup' },
    });
  });
});

describe('external authentication entry points', () => {
  it('builds a provider start URL with a same-origin return path', () => {
    expect(externalAuthStartUrl('google', '/projects/project-a?tab=history')).toBe(
      '/auth/google/start?return_to=%2Fprojects%2Fproject-a%3Ftab%3Dhistory',
    );
    expect(externalAuthStartUrl('github', 'https://attacker.example')).toBe(
      '/auth/github/start?return_to=%2F',
    );
  });
});

describe('local account isolation', () => {
  it('clears private state before adopting a different account', async () => {
    let username = 'ada';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'https://polycolab.example').pathname;
        return new Response(
          JSON.stringify(
            path === '/auth/config'
              ? { mode: 'local' }
              : { authenticated: true, username, display_name: username },
          ),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    const resetPrivateState = vi.fn();
    const auth = new Auth(resetPrivateState);

    await auth.initialize();
    expect(auth.label).toBe('ada');
    expect(resetPrivateState).not.toHaveBeenCalled();

    username = 'grace';
    await auth.initialize();

    expect(resetPrivateState).toHaveBeenCalledOnce();
    expect(auth.label).toBe('grace');
  });

  it('clears private state after a successful sign-out', async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'https://polycolab.example').pathname;
      if (path === '/auth/logout') return new Response(null, { status: 204 });
      return new Response(
        JSON.stringify(
          path === '/auth/config' ? { mode: 'local' } : { authenticated: true, username: 'ada' },
        ),
        { headers: { 'Content-Type': 'application/json' } },
      );
    });
    vi.stubGlobal('fetch', fetch);
    const resetPrivateState = vi.fn();
    const auth = new Auth(resetPrivateState);
    await auth.initialize();

    await auth.signOut();

    expect(auth.signedIn).toBe(false);
    expect(resetPrivateState).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenLastCalledWith(
      '/auth/logout',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });

  it('expires an authenticated session once and keeps sign-in available', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'https://polycolab.example').pathname;
        return new Response(
          JSON.stringify(
            path === '/auth/config' ? { mode: 'local' } : { authenticated: true, username: 'ada' },
          ),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    const resetPrivateState = vi.fn();
    const auth = new Auth(resetPrivateState);
    await auth.initialize();

    await auth.expireSession();
    await auth.expireSession();

    expect(auth.signedIn).toBe(false);
    expect(auth.notice).toBe('Your session expired. Sign in again.');
    expect(resetPrivateState).toHaveBeenCalledOnce();
  });

  it('clears local authenticated state after canonical password reset', async () => {
    const resetPrivateState = vi.fn();
    const auth = new Auth(resetPrivateState);
    auth.configuration = { mode: 'local' };
    auth.account = { authenticated: true, username: 'ada' };

    await auth.completePasswordReset();

    expect(auth.signedIn).toBe(false);
    expect(auth.notice).toContain('Every existing session was revoked');
    expect(resetPrivateState).toHaveBeenCalledOnce();
  });

  it('clears an OIDC user already marked expired and removes its stored session once', async () => {
    const resetPrivateState = vi.fn();
    const removeUser = vi.fn().mockResolvedValue(undefined);
    const auth = new Auth(resetPrivateState);
    auth.configuration = { mode: 'oidc' };
    auth.user = {
      expired: true,
      profile: { sub: 'ada' },
    } as NonNullable<typeof auth.user>;
    auth.manager = { removeUser } as unknown as NonNullable<typeof auth.manager>;

    expect(auth.signedIn).toBe(false);
    await auth.expireSession();
    await auth.expireSession();

    expect(auth.user).toBeNull();
    expect(auth.notice).toBe('Your session expired. Sign in again.');
    expect(resetPrivateState).toHaveBeenCalledOnce();
    expect(removeUser).toHaveBeenCalledOnce();
  });
});
