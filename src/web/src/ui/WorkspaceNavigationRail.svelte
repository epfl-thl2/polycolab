<script lang="ts">
  import * as Tooltip from '../lib/components/ui/tooltip';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import AccountMenu from './AccountMenu.svelte';
  import type { Auth } from '../svelte-lib/auth.svelte';
  import { accountHref } from '../lib/account-navigation';
  import {
    FolderKanban,
    PanelsLeftBottom,
    Files,
    Map as MapIcon,
    History,
    Plug,
    Settings,
    UserRound,
  } from '@lucide/svelte';
  let {
    auth,
    projectId,
    section,
    canManage,
    onNavigate,
    expanded = false,
    showBrand = true,
  }: {
    auth: Auth;
    projectId: string;
    section: string;
    canManage: boolean;
    onNavigate: (href: string) => void;
    expanded?: boolean;
    showBrand?: boolean;
  } = $props();
  let accountError = $state('');
  async function signOut() {
    accountError = '';
    try {
      await auth.signOut();
    } catch {
      accountError = 'Sign-out failed. Please retry.';
    }
  }
  const links = [
    ['overview', 'Project', FolderKanban],
    ['sessions', 'Workspace', PanelsLeftBottom],
    ['research', 'Research objects', Files],
    ['map', 'Map', MapIcon],
    ['activity', 'Activity', History],
  ] as const;
  function navigate(event: MouseEvent, href: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    event.preventDefault();
    onNavigate(href);
  }
</script>

{#snippet navLink(
  href: string,
  label: string,
  Icon: typeof FolderKanban,
  active = false,
  extraClass = '',
)}
  <Tooltip.Root disabled={expanded}>
    <Tooltip.Trigger onclick={(event) => navigate(event, href)}>
      {#snippet child({ props })}
        <a
          {...props}
          class={`rail-link ${extraClass}`}
          {href}
          aria-label={label}
          aria-current={active ? 'page' : undefined}
        >
          <Icon size={18} aria-hidden="true" /><span class="label">{label}</span>
        </a>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content side="right">{label}</Tooltip.Content>
  </Tooltip.Root>
{/snippet}

<Tooltip.Provider delayDuration={250}>
  <div class="rail-slot" class:reserved={expanded}>
    <aside class="navigation-rail" class:open={expanded} aria-label="Workspace navigation">
      {#if showBrand}
        <Tooltip.Root disabled={expanded}>
          <Tooltip.Trigger>
            {#snippet child({ props })}
              <a {...props} class="rail-brand" href="/workspaces" aria-label="Polycolab workspaces">
                <img src="/brand/polycolab-mark.png" alt="" />
                <span class="label">Polycolab</span>
              </a>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content side="right">Workspaces</Tooltip.Content>
        </Tooltip.Root>
      {/if}
      <nav class="main-links" aria-label="Workspace sections">
        {#each links as [id, label, Icon] (id)}
          {@render navLink(`/workspaces/${projectId}/${id}`, label, Icon, section === id)}
        {/each}
      </nav>
      <nav class="footer-links" aria-label="Workspace tools">
        {@render navLink(
          `/workspaces/${projectId}/agent-connect`,
          'Agent connect',
          Plug,
          section === 'agent-connect',
        )}
        {#if canManage}
          {@render navLink(
            `/workspaces/${projectId}/settings`,
            'Workspace settings',
            Settings,
            section === 'settings',
          )}
        {/if}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            class="rail-link profile-link"
            aria-label="Open account menu"
            title="Account"
            disabled={!auth.loaded}
          >
            <UserRound size={18} aria-hidden="true" /><span class="label">Account</span>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content
            class="w-60"
            side="right"
            align="end"
            sideOffset={8}
            preventScroll={false}
          >
            {#if auth.signedIn}
              <AccountMenu {auth} onSignOut={() => void signOut()} />
            {:else}
              <DropdownMenu.Item>
                {#snippet child({ props })}
                  <a {...props} href={accountHref('signin', `/workspaces/${projectId}/${section}`)}
                    >Sign in</a
                  >
                {/snippet}
              </DropdownMenu.Item>
              <DropdownMenu.Item>
                {#snippet child({ props })}
                  <a {...props} href={accountHref('signup', `/workspaces/${projectId}/${section}`)}
                    >Create account</a
                  >
                {/snippet}
              </DropdownMenu.Item>
            {/if}
          </DropdownMenu.Content>
        </DropdownMenu.Root>
        {#if accountError}<p role="alert">{accountError}</p>{/if}
      </nav>
    </aside>
  </div>
</Tooltip.Provider>

<style>
  .rail-slot {
    position: relative;
    flex: 0 0 56px;
    width: 56px;
    height: 100%;
  }
  .rail-slot.reserved {
    flex-basis: 220px;
    width: 220px;
  }
  .navigation-rail {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 30;
    display: flex;
    flex-direction: column;
    gap: 14px;
    width: 56px;
    overflow: hidden;
    padding: 10px 7px;
    border-right: 1px solid var(--border);
    color: var(--foreground);
    background: var(--sidebar, var(--background));
  }
  .navigation-rail.open {
    width: 220px;
  }
  nav {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .footer-links {
    margin-top: auto;
  }
  :global(.navigation-rail .rail-link) {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 40px;
    padding: 10px 11px;
    flex-shrink: 0;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--muted-foreground);
    text-decoration: none;
    font-size: 12px;
    font-weight: 500;
    text-align: left;
    cursor: pointer;
  }
  :global(.navigation-rail .rail-link svg) {
    flex-shrink: 0;
  }
  :global(.navigation-rail .rail-link:hover),
  :global(.navigation-rail .rail-link[aria-current='page']),
  :global(.navigation-rail .rail-link[data-state='open']) {
    background: var(--brand-soft);
    color: var(--brand-strong);
  }
  .rail-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 40px;
    padding: 6px;
    color: var(--foreground);
    font-size: 15px;
    font-weight: 600;
    text-decoration: none;
  }
  .rail-brand img {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
  }
  :global(.navigation-rail .rail-link:focus-visible) {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  .label {
    opacity: 0;
    white-space: nowrap;
    visibility: hidden;
  }
  .open .label {
    opacity: 1;
    visibility: visible;
  }
  :global(.navigation-rail .profile-link) {
    margin-top: 7px;
  }
</style>
