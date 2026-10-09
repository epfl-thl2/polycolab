<script lang="ts">
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { createAccountRecoveryApi } from '../lib/account-recovery-api';
  import { ApiError } from '../lib/research-api';
  import { workspace } from '../svelte-lib/context';

  let { mode }: { mode: 'verify' | 'request' | 'confirm' } = $props();
  const { auth } = workspace();
  const recovery = createAccountRecoveryApi();
  let email = $state('');
  let token = $state(
    browser ? (new URLSearchParams(location.search).get('token') ?? '').slice(0, 512) : '',
  );
  let password = $state('');
  let confirmation = $state('');
  let busy = $state(false);
  let error = $state('');
  let accepted = $state(false);

  const invalidMessage = (reason: unknown) => {
    if (reason instanceof ApiError && reason.code === 'invalid_recovery')
      return 'This link is invalid, expired, or has already been used. Request a new one.';
    if (reason instanceof ApiError && reason.code === 'recovery_rate_limited')
      return 'Too many recovery requests. Wait before trying again.';
    return 'Recovery could not be completed. Please retry.';
  };

  async function submit() {
    busy = true;
    error = '';
    try {
      if (mode === 'request') await recovery.requestPasswordReset(email.trim());
      else if (mode === 'verify') await recovery.verifyEmail(token);
      else {
        if (password !== confirmation) {
          error = 'Passwords do not match.';
          return;
        }
        await recovery.confirmPasswordReset(token, password);
        password = '';
        confirmation = '';
        token = '';
        await auth.completePasswordReset();
        await goto('/signin');
        return;
      }
      accepted = true;
    } catch (reason) {
      error = invalidMessage(reason);
    } finally {
      busy = false;
    }
  }
</script>

<main id="main" class="page narrow auth-page" tabindex="-1">
  <div class="auth-card">
    {#if mode === 'request'}
      <h1>Reset your password</h1>
      {#if accepted}<div class="notice" role="status">
          <strong>Check your email.</strong>
          <p>
            If that address belongs to a verified Polycolab account, a reset link has been sent.
          </p>
          <a href="/signin">Return to sign in</a>
        </div>{:else}<p class="muted">
          Recovery works only after an email address has been verified in account settings.
        </p>
        <form
          onsubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Field.Label
            >Email<Input
              type="email"
              autocomplete="email"
              required
              bind:value={email}
            /></Field.Label
          >
          {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
          <Button type="submit" disabled={busy}>{busy ? 'Requesting…' : 'Send reset link'}</Button>
        </form>{/if}
    {:else if mode === 'verify'}
      <h1>Verify your recovery email</h1>
      {#if accepted}<div class="notice" role="status">
          <strong>Email verified.</strong>
          <p>You can now use this address to recover your built-in account.</p>
          <a href="/settings/recovery">Return to recovery settings</a>
        </div>{:else}<p class="muted">
          Confirm this link deliberately. Verification links expire after 24 hours and work once.
        </p>
        {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
        <Button type="submit" disabled={busy || !token} onclick={() => void submit()}>
          {busy ? 'Verifying…' : 'Verify email'}
        </Button>{/if}
    {:else}
      <h1>Choose a new password</h1>
      {#if accepted}<div class="notice" role="status">
          <strong>Password changed.</strong>
          <p>Every existing session was revoked. Sign in again with your new password.</p>
          <a href="/signin">Sign in</a>
        </div>{:else}<p class="muted">
          Reset links expire after 30 minutes and work once. Your new password signs out every
          existing session.
        </p>
        <form
          onsubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Field.Label
            >New password<Input
              type="password"
              autocomplete="new-password"
              minlength={12}
              maxlength={256}
              required
              bind:value={password}
            /></Field.Label
          >
          <Field.Label
            >Confirm new password<Input
              type="password"
              autocomplete="new-password"
              minlength={12}
              maxlength={256}
              required
              bind:value={confirmation}
            /></Field.Label
          >
          {#if error}<Alert.Root variant="destructive" role="alert">{error}</Alert.Root>{/if}
          <Button type="submit" disabled={busy || !token}
            >{busy ? 'Changing…' : 'Change password'}</Button
          >
        </form>{/if}
    {/if}
  </div>
</main>
