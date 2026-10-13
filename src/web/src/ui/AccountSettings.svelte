<script lang="ts">
  import AgentApiKeys from './AgentApiKeys.svelte';
  import { UserRound, ShieldCheck, Mail, Bot, KeyRound } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import { projectContext } from '../svelte-lib/context';
  let { path }: { path: string } = $props();
  const { auth, capabilities } = projectContext();
  const section = $derived(
    path === '/settings/api-keys'
      ? 'agent-keys'
      : path === '/settings/security'
        ? 'security'
        : path === '/settings/recovery'
          ? 'recovery'
          : path === '/settings/model-providers'
            ? 'providers'
            : 'general',
  );
</script>

<main id="main" class="page settings-layout" tabindex="-1">
  <header class="settings-heading"><h1>Settings</h1></header>
  <aside class="settings-navigation">
    <nav aria-label="Settings sections">
      <a href="/settings" aria-current={section === 'general' ? 'page' : undefined}
        ><UserRound aria-hidden="true" />Profile</a
      >
      {#if capabilities?.enabled('email_recovery')}<a
          href="/settings/recovery"
          aria-current={section === 'recovery' ? 'page' : undefined}
          ><Mail aria-hidden="true" />Account recovery</a
        >{/if}
      <div class="settings-access-group" role="group" aria-labelledby="settings-access-title">
        <h2 id="settings-access-title">Access</h2>
        <a href="/settings/security" aria-current={section === 'security' ? 'page' : undefined}
          ><ShieldCheck aria-hidden="true" />Password and authentication</a
        >

        <a href="/settings/api-keys" aria-current={section === 'agent-keys' ? 'page' : undefined}>
          <KeyRound aria-hidden="true" />API keys
        </a>
        <a
          href="/settings/model-providers"
          aria-current={section === 'providers' ? 'page' : undefined}
        >
          <Bot aria-hidden="true" />Model providers
        </a>
      </div>
    </nav>
  </aside>

  <div class="settings-surface">
    {#if section === 'recovery' && capabilities?.enabled('email_recovery')}
      {#await import('./RecoverySettings.svelte') then module}<module.default />{/await}
    {:else if section === 'providers'}
      {#if capabilities?.enabled('agent_execution')}
        {#await import('./Providers.svelte') then module}<module.default />{/await}
      {:else}
        <section class="settings-content" aria-labelledby="providers-unavailable-title">
          <header class="settings-section-heading">
            <h2 id="providers-unavailable-title">Model providers</h2>
          </header>
          <div class="settings-profile-action">
            <div>
              <h2>Built-in agents are unavailable</h2>
              <p class="muted">
                Your deployment administrator needs to enable agent execution before you can
                configure AI providers.
              </p>
            </div>
            <Button disabled variant="outline">Add model provider</Button>
          </div>
        </section>
      {/if}
    {:else if section === 'agent-keys'}
      <AgentApiKeys />
    {:else if section === 'security'}
      <section class="settings-content" aria-labelledby="security-title">
        <header class="settings-section-heading">
          <h2 id="security-title">Password and authentication</h2>
        </header>
        <div class="settings-sections">
          <section>
            <h2>Reset password</h2>
            {#if auth.configuration?.mode === 'oidc'}
              <p class="muted">Your password is managed by your identity provider.</p>
              <Button variant="outline" disabled>Reset password</Button>
            {:else if capabilities?.enabled('email_recovery')}
              <p class="muted">Send a reset link to your verified recovery email.</p>
              <Button variant="outline" href="/forgot-password">Reset password</Button>
            {:else}
              <p class="muted">
                Password reset is unavailable on this deployment. Contact your administrator for
                help.
              </p>
              <Button variant="outline" disabled>Reset password</Button>
            {/if}
          </section>
        </div>
      </section>
    {:else}
      <section class="settings-content" aria-labelledby="settings-title">
        <header class="settings-section-heading"><h2 id="settings-title">Profile</h2></header>
        <dl class="settings-details">
          <div>
            <dt>Display name</dt>
            <dd>{auth.label}</dd>
          </div>
          {#if auth.account?.username || auth.user?.profile.preferred_username}
            <div>
              <dt>Username</dt>
              <dd>{auth.account?.username ?? auth.user?.profile.preferred_username}</dd>
            </div>
          {/if}
        </dl>
      </section>
    {/if}
  </div>
</main>
