import type { User, UserManager } from 'oidc-client-ts';
import { accountReturnPath } from '../lib/account-navigation';

type Account = {
  authenticated: boolean;
  username?: string;
  display_name?: string;
};
export type Configuration = {
  mode: 'local' | 'oidc';
  registration_mode?: 'open' | 'invitation' | 'closed';
  social_providers?: Array<'google' | 'github'>;
  issuer?: string;
  client_id?: string;
  audience?: string;
};

export const authConfigurationCacheKey = 'polycolab.auth-configuration.v1';
const authConfigurationCacheTtlMs = 5 * 60 * 1000;
type CachedConfiguration = { expires_at: number; configuration: Configuration };

function normalizedConfiguration(value: unknown): Configuration | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const candidate = value as Record<string, unknown>;
  if (candidate.mode !== 'local' && candidate.mode !== 'oidc') return undefined;
  if (
    candidate.registration_mode !== undefined &&
    (typeof candidate.registration_mode !== 'string' ||
      !['open', 'invitation', 'closed'].includes(candidate.registration_mode))
  )
    return undefined;
  if (
    candidate.social_providers !== undefined &&
    (!Array.isArray(candidate.social_providers) ||
      candidate.social_providers.some((provider) => provider !== 'google' && provider !== 'github'))
  )
    return undefined;
  const configuration: Configuration = { mode: candidate.mode };
  if (candidate.registration_mode !== undefined)
    configuration.registration_mode = candidate.registration_mode as NonNullable<
      Configuration['registration_mode']
    >;
  if (candidate.social_providers !== undefined)
    configuration.social_providers = [...candidate.social_providers] as NonNullable<
      Configuration['social_providers']
    >;
  if (candidate.mode === 'local') return configuration;
  if (
    typeof candidate.issuer !== 'string' ||
    !candidate.issuer ||
    typeof candidate.client_id !== 'string' ||
    !candidate.client_id ||
    typeof candidate.audience !== 'string' ||
    !candidate.audience
  )
    return undefined;
  return {
    ...configuration,
    issuer: candidate.issuer,
    client_id: candidate.client_id,
    audience: candidate.audience,
  };
}

function cacheStorage() {
  try {
    return typeof sessionStorage === 'undefined' ? undefined : sessionStorage;
  } catch {
    return undefined;
  }
}

export function readCachedAuthConfiguration(now = Date.now()) {
  const storage = cacheStorage();
  if (!storage) return undefined;
  try {
    const raw = storage.getItem(authConfigurationCacheKey);
    if (!raw) return undefined;
    const cached = JSON.parse(raw) as Partial<CachedConfiguration>;
    const configuration = normalizedConfiguration(cached.configuration);
    if (typeof cached.expires_at !== 'number' || cached.expires_at <= now || !configuration) {
      storage.removeItem(authConfigurationCacheKey);
      return undefined;
    }
    return configuration;
  } catch {
    try {
      storage.removeItem(authConfigurationCacheKey);
    } catch {
      // Storage is an optional performance optimization.
    }
    return undefined;
  }
}

function writeCachedAuthConfiguration(configuration: Configuration, now = Date.now()) {
  const storage = cacheStorage();
  if (!storage) return;
  try {
    storage.setItem(
      authConfigurationCacheKey,
      JSON.stringify({ expires_at: now + authConfigurationCacheTtlMs, configuration }),
    );
  } catch {
    // Storage is an optional performance optimization.
  }
}

function clearCachedAuthConfiguration() {
  try {
    cacheStorage()?.removeItem(authConfigurationCacheKey);
  } catch {
    // Storage is an optional performance optimization.
  }
}

export type ExternalAuthProvider = NonNullable<Configuration['social_providers']>[number];

export function externalAuthStartUrl(provider: ExternalAuthProvider, returnTo = '/projects') {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? '';
  const query = new URLSearchParams({ return_to: safeReturnPath(returnTo) });
  return `${baseUrl}/auth/${provider}/start?${query}`;
}

export function safeReturnPath(value: unknown, origin = location.origin) {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    value.includes('\\')
  )
    return '/';
  try {
    const target = new URL(value, origin);
    if (target.origin !== origin) return '/';
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return '/';
  }
}

const authenticationErrorMessage = (status: number, code?: string) => {
  const registrationErrors: Record<string, string> = {
    registration_closed: 'Account registration is closed.',
    setup_required: 'The deployment administrator has not been initialized.',
    registration_conflict: 'That username is already registered.',
    invalid_registration_invitation: 'That invitation code is invalid or expired.',
    registration_request_invalid: 'Check the registration details and try again.',
    validation_error: 'Check the registration details and try again.',
    registration_request_too_large: 'The registration request is too large.',
    registration_rate_limited: 'Too many registration attempts. Please wait and retry.',
    login_rate_limited: 'Too many sign-in attempts. Please wait and retry.',
  };
  if (code && registrationErrors[code]) return registrationErrors[code];
  return status === 401
    ? 'Sign-in failed. Check your credentials.'
    : 'Authentication is unavailable. Please retry.';
};

export async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    let code: string | undefined;
    try {
      const body = (await response.clone().json()) as { error?: { code?: unknown } };
      if (typeof body.error?.code === 'string') code = body.error.code;
    } catch {
      // Authentication errors remain content-free when the response is malformed.
    }
    throw new Error(authenticationErrorMessage(response.status, code));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export class Auth {
  loaded = $state(false);
  configuration = $state<Configuration>();
  account = $state<Account>();
  user = $state<User | null>(null);
  error = $state('');
  notice = $state('');
  manager?: UserManager;
  signedIn = $derived(
    this.configuration?.mode === 'local'
      ? Boolean(this.account?.authenticated)
      : Boolean(this.user && !this.user.expired),
  );
  label = $derived(
    this.account?.display_name ?? this.account?.username ?? this.user?.profile.name ?? 'Signed in',
  );
  private cleanup?: () => void;
  constructor(private resetPrivateState: () => void) {}
  private async fetchConfiguration() {
    const response = await authRequest<unknown>('/auth/config');
    const configuration = normalizedConfiguration(response);
    if (!configuration) throw new Error('Authentication is not configured.');
    writeCachedAuthConfiguration(configuration);
    return configuration;
  }
  private resetProvider() {
    this.cleanup?.();
    this.cleanup = undefined;
    this.manager = undefined;
  }
  private async initializeWith(configuration: Configuration) {
    this.configuration = configuration;
    if (configuration.mode === 'local') {
      this.user = null;
      const previous = this.account;
      const account = await authRequest<Account>('/auth/me');
      if (
        previous &&
        (previous.authenticated !== account.authenticated || previous.username !== account.username)
      )
        this.resetPrivateState();
      this.account = account;
      return;
    }
    this.account = undefined;
    const { UserManager, WebStorageStateStore } = await import('oidc-client-ts');
    const origin = location.origin;
    const manager = (this.manager = new UserManager({
      authority: configuration.issuer!,
      client_id: configuration.client_id!,
      redirect_uri: `${origin}/oidc/callback`,
      silent_redirect_uri: `${origin}/oidc/silent-callback`,
      post_logout_redirect_uri: `${origin}/`,
      response_type: 'code',
      scope: 'openid profile email offline_access',
      extraQueryParams: { audience: configuration.audience! },
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: sessionStorage }),
    }));
    const loaded = (user: User) => {
      if (this.user?.profile.sub !== user.profile.sub) this.resetPrivateState();
      this.user = user;
    };
    const unloaded = () => {
      const hadUser = Boolean(this.user);
      this.user = null;
      if (hadUser) this.resetPrivateState();
    };
    const expired = () => void this.expireSession();
    manager.events.addUserLoaded(loaded);
    manager.events.addUserUnloaded(unloaded);
    manager.events.addAccessTokenExpired(expired);
    this.cleanup = () => {
      manager.events.removeUserLoaded(loaded);
      manager.events.removeUserUnloaded(unloaded);
      manager.events.removeAccessTokenExpired(expired);
      manager.stopSilentRenew();
    };
    if (location.pathname === '/oidc/silent-callback') {
      await manager.signinSilentCallback();
      return;
    }
    const user =
      location.pathname === '/oidc/callback'
        ? await manager.signinRedirectCallback()
        : await manager.getUser();
    this.user = user && !user.expired ? user : null;
    if (location.pathname === '/oidc/callback') {
      const target = (user?.state as { returnTo?: string })?.returnTo;
      location.replace(safeReturnPath(target));
    }
  }
  async initialize() {
    this.loaded = false;
    this.error = '';
    this.notice = '';
    this.resetProvider();
    const cached = readCachedAuthConfiguration();
    try {
      await this.initializeWith(cached ?? (await this.fetchConfiguration()));
    } catch (error) {
      let finalError = error;
      if (cached) {
        clearCachedAuthConfiguration();
        this.resetProvider();
        try {
          await this.initializeWith(await this.fetchConfiguration());
          return;
        } catch (retryError) {
          finalError = retryError;
        }
      }
      this.error = finalError instanceof Error ? finalError.message : 'Authentication unavailable.';
      this.account = undefined;
      this.user = null;
      this.resetPrivateState();
    } finally {
      this.loaded = true;
    }
  }
  token = async () => {
    if (!this.manager) return undefined;
    let user = await this.manager.getUser();
    // Anonymous shared reads must not start an OIDC login or silent iframe flow.
    if (!user) return undefined;
    if (user.expired) {
      try {
        user = await this.manager.signinSilent();
      } catch {
        await this.expireSession();
        throw new Error('Your session expired. Sign in again.');
      }
    }
    if (!user) throw new Error('Sign in again.');
    this.user = user;
    return user.access_token;
  };
  async signIn(returnTo = location.pathname + location.search) {
    await this.manager?.signinRedirect({
      state: { returnTo: accountReturnPath(returnTo) },
    });
  }
  async signUp(returnTo = '/projects') {
    await this.manager?.signinRedirect({
      state: { returnTo: accountReturnPath(returnTo) },
      extraQueryParams: { screen_hint: 'signup' },
    });
  }
  async signOut() {
    if (this.configuration?.mode === 'local') {
      await authRequest('/auth/logout', { method: 'POST' });
      this.account = { authenticated: false };
    } else {
      await this.manager?.signoutRedirect();
    }
    this.resetPrivateState();
  }
  async expireSession() {
    const hadSession =
      this.configuration?.mode === 'local'
        ? Boolean(this.account?.authenticated)
        : Boolean(this.user);
    if (!hadSession) return;
    const manager = this.manager;
    if (this.configuration?.mode === 'local')
      this.account = { ...this.account, authenticated: false };
    else this.user = null;
    this.notice = 'Your session expired. Sign in again.';
    this.resetPrivateState();
    try {
      await manager?.removeUser();
    } catch {
      // The in-memory session is already closed; storage cleanup is best effort.
    }
  }
  async completePasswordReset() {
    const manager = this.manager;
    this.account = { authenticated: false };
    this.user = null;
    this.notice = 'Password changed. Every existing session was revoked; sign in again.';
    this.resetPrivateState();
    try {
      await manager?.removeUser();
    } catch {
      // Canonical sessions are already revoked; local provider storage cleanup is best effort.
    }
  }
  dispose() {
    this.cleanup?.();
  }
}
