<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import * as Field from '../lib/components/ui/field';
  import { authRequest } from '../svelte-lib/auth.svelte';
  import { createAccountRecoveryApi, type AccountEmail } from '../lib/account-recovery-api';
  import { explain } from '../svelte-lib/context';
  const api = createAccountRecoveryApi();
  let emailState = $state<AccountEmail>();
  let email = $state('');
  let password = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  async function perform(action: () => Promise<unknown>) {
    busy = true;
    error = '';
    notice = '';
    try {
      await action();
      emailState = await api.email();
    } catch (reason) {
      const failure = reason as { code?: string; status?: number };
      error =
        failure.code === 'recovery_conflict'
          ? 'This email is already verified for another account.'
          : failure.status === 401
            ? 'Sign in again and retry with your current password.'
            : explain(reason);
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void perform(async () => {});
  });
  async function save() {
    await perform(async () => {
      try {
        await authRequest('/auth/reauthenticate', {
          method: 'POST',
          body: JSON.stringify({ password }),
        });
      } finally {
        password = '';
      }
      await api.changeEmail(email.trim());
      notice = 'Check your email for a verification link.';
    });
  }
</script>

<section class="settings-content">
  <h2 class="sr-only">Account recovery</h2>
  <p>Your account is already active. Verify an email address to recover access to it.</p>
  {#if !emailState?.verified_email}<p>No verified recovery email.</p>{/if}
  {#if emailState?.verified_email}<p>Verified: {emailState.verified_email}</p>{/if}
  {#if emailState?.pending_email}<p>Pending verification: {emailState.pending_email}</p>
    {#if emailState.verified_email}<p>
        Your current verified address remains available until the replacement is verified.
      </p>{/if}
    <Button
      disabled={busy}
      onclick={() =>
        perform(async () => {
          await api.resendVerification();
          notice = 'Verification email requested; the earlier link no longer works.';
        })}>Resend verification</Button
    >{/if}
  <form
    onsubmit={(event) => {
      event.preventDefault();
      void save();
    }}
  >
    <Field.Label>Recovery email<Input type="email" required bind:value={email} /></Field.Label>
    <Field.Label
      >Current password<Input
        type="password"
        autocomplete="current-password"
        required
        bind:value={password}
      /></Field.Label
    >
    <Button type="submit" disabled={busy}>Verify recovery email</Button>
  </form>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
</section>
