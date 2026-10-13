<script lang="ts">
  import { Eye, EyeOff } from '@lucide/svelte';
  import ErrorToast from './ErrorToast.svelte';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Auth, authRequest } from '../svelte-lib/auth.svelte';
  import { accountHref, accountReturnPath } from '../lib/account-navigation';
  let {
    auth,
    mode = 'signin',
    returnTo = '/projects',
    onSignedIn,
  }: {
    auth: Auth;
    mode?: 'signin' | 'signup';
    returnTo?: string;
    onSignedIn?: () => void;
  } = $props();
  async function socialSignIn(provider: 'google' | 'github') {
    busy = true;
    error = '';
    try {
      const response = await authRequest<{ authorization_url: string }>(
        `/auth/social/${provider}/start`,
        { method: 'POST', body: JSON.stringify({ return_path: destination }) },
      );
      window.location.assign(response.authorization_url);
    } catch (reason) {
      error = reason instanceof Error ? reason.message : 'Could not start sign in.';
    } finally {
      busy = false;
    }
  }
  async function providerSignIn() {
    busy = true;
    error = '';
    try {
      if (mode === 'signup') await auth.signUp(destination);
      else await auth.signIn(destination);
    } catch (reason) {
      error = reason instanceof Error ? reason.message : 'Could not start sign in.';
    } finally {
      busy = false;
    }
  }
  const destination = $derived(accountReturnPath(returnTo));
  let username = $state('');
  const passwordId = $props.id();
  let password = $state('');
  let showPassword = $state(false);
  let passwordConfirmation = $state('');
  let displayName = $state('');
  let invitationCode = $state('');
  let busy = $state(false);
  let error = $state('');
  const registrationMode = $derived(auth.configuration?.registration_mode ?? 'closed');
  const registration = $derived(
    mode === 'signup' && auth.configuration?.mode === 'local' && registrationMode !== 'closed',
  );
  const localRegistrationUnavailable = $derived(
    mode === 'signup' && auth.configuration?.mode === 'local' && registrationMode === 'closed',
  );
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      if (registration && password !== passwordConfirmation) {
        error = 'Passwords do not match.';
        return;
      }
      await authRequest(registration ? '/auth/register' : '/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          username,
          password,
          ...(registration
            ? {
                display_name: displayName || undefined,
                ...(registration
                  ? {
                      ...(registrationMode === 'invitation'
                        ? { invitation_code: invitationCode }
                        : {}),
                    }
                  : {}),
              }
            : {}),
        }),
      });
      showPassword = false;
      password = '';
      passwordConfirmation = '';
      await auth.initialize();
      if (auth.signedIn) onSignedIn?.();
    } catch (reason) {
      error =
        reason instanceof Error
          ? reason.message
          : registration
            ? 'Could not create the account.'
            : 'Could not sign in.';
    } finally {
      busy = false;
    }
  }
</script>

<div class="auth-card-header">
  <h1>{mode === 'signup' ? 'Create account' : 'Sign in'}</h1>
</div>
<ErrorToast message={error || auth.error || auth.notice || ''} />
{#if auth.error}
  <Button type="submit" onclick={() => auth.initialize()}>Retry connection</Button>
{:else if auth.signedIn}<div class="auth-choice">
    <p>You are signed in as <strong>{auth.label}</strong>.</p>
    <Button href={destination}>Continue</Button>
  </div>
{:else if auth.configuration?.mode === 'oidc'}<div class="auth-choice">
    <Button class="auth-primary" type="button" disabled={busy} onclick={providerSignIn}
      >{mode === 'signup' ? 'Continue to create account' : 'Sign in'}</Button
    >
    <p class="muted auth-alternative">
      {#if mode === 'signup'}Already have an account?{:else}Don't have an account?{/if}
      <a href={accountHref(mode === 'signup' ? 'signin' : 'signup', destination)}
        >{mode === 'signup' ? 'Sign in' : 'Sign up'}</a
      >
    </p>
  </div>
{:else}
  {#if localRegistrationUnavailable}<div class="panel auth-access-note">
      <h2>Account creation is managed by this deployment</h2>
      <p class="muted">
        Ask the Polycolab administrator or your research-team contact to create an account for you.
      </p>
      <Button variant="outline" href={accountHref('signin', destination)}>Return to sign in</Button>
    </div>
  {:else}
    <form onsubmit={submit}>
      {#if registration}<Field.Label>
          <span>Display name <span class="muted">(optional)</span></span><Input
            aria-label="Display name"
            autocomplete="name"
            bind:value={displayName}
          /></Field.Label
        >{/if}
      <Field.Label
        >Username<Input autocomplete="username" required bind:value={username} /></Field.Label
      >
      {#if registration}
        {#if registrationMode === 'invitation'}<Field.Label
            >Invitation code<Input
              autocomplete="one-time-code"
              required
              bind:value={invitationCode}
            /></Field.Label
          >{/if}{/if}
      <div class="password-field">
        <Field.Label for={passwordId}>Password</Field.Label>
        <div class="password-input">
          <Input
            id={passwordId}
            type={showPassword ? 'text' : 'password'}
            autocomplete={registration ? 'new-password' : 'current-password'}
            minlength={12}
            aria-describedby={registration ? `${passwordId}-hint` : undefined}
            required
            bind:value={password}
            class="pr-11"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="password-toggle"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            aria-controls={passwordId}
            onclick={() => (showPassword = !showPassword)}
          >
            {#if showPassword}<EyeOff aria-hidden="true" />{:else}<Eye aria-hidden="true" />{/if}
          </Button>
        </div>
        {#if registration}<p id={`${passwordId}-hint`} class="password-help">
            Use at least 12 characters.
          </p>{/if}
      </div>
      {#if registration}<Field.Label
          >Confirm password<Input
            type="password"
            autocomplete="new-password"
            minlength={12}
            required
            bind:value={passwordConfirmation}
          /></Field.Label
        >{/if}
      <Button class="auth-primary" type="submit" disabled={busy}
        >{busy
          ? registration
            ? 'Creating account…'
            : 'Signing in…'
          : registration
            ? 'Create account'
            : 'Sign in'}</Button
      >
    </form>
    <div class="auth-divider" aria-hidden="true">or continue with</div>
    <div class="social-sign-in" role="group" aria-label="Social sign-in">
      {#each ['google', 'github'] as provider (provider)}
        {@const configured = auth.configuration?.social_providers?.includes(
          provider as 'google' | 'github',
        )}
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          href={configured ? undefined : '/404'}
          onclick={configured ? () => socialSignIn(provider as 'google' | 'github') : undefined}
        >
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            {#if provider === 'google'}
              <path
                d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36ZM12 22c2.7 0 4.96-.9 6.62-2.41l-3.24-2.51c-.9.6-2.05.96-3.38.96-2.6 0-4.81-1.76-5.6-4.12H3.06v2.59A10 10 0 0 0 12 22ZM6.4 13.92a6 6 0 0 1 0-3.84V7.49H3.06a10 10 0 0 0 0 9.02l3.34-2.59ZM12 5.96c1.47 0 2.79.5 3.82 1.49l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.94 5.49l3.34 2.59A5.99 5.99 0 0 1 12 5.96Z"
              />
            {:else}
              <path
                d="M12 .3a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.23c-3.34.73-4.04-1.42-4.04-1.42-.55-1.39-1.33-1.76-1.33-1.76-1.09-.75.08-.73.08-.73 1.2.08 1.84 1.23 1.84 1.23 1.07 1.83 2.81 1.3 3.5.99.1-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.25 2.88.12 3.18.77.84 1.23 1.91 1.23 3.22 0 4.6-2.8 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.3c0 .32.22.7.83.58A12 12 0 0 0 12 .3Z"
              />
            {/if}
          </svg>
          {provider === 'google' ? 'Google' : 'GitHub'}
        </Button>
      {/each}
    </div>
    <p class="muted auth-alternative">
      {#if mode === 'signup'}Already have an account?{:else}Don't have an account?{/if}
      <a href={accountHref(mode === 'signup' ? 'signin' : 'signup', destination)}
        >{mode === 'signup' ? 'Sign in' : 'Sign up'}</a
      >
    </p>{/if}
{/if}

<style>
  .social-sign-in {
    display: grid;
    gap: 10px;
  }
  .password-field {
    display: grid;
    gap: 8px;
  }
  .password-help {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--muted-foreground);
  }
  .social-sign-in :global([data-slot='button']) {
    min-height: 40px;
  }
  .password-input {
    position: relative;
  }
  .password-input :global(.password-toggle) {
    position: absolute;
    right: 2px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--muted-foreground);
  }
</style>
