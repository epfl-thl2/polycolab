<script lang="ts">
  import * as Avatar from '../lib/components/ui/avatar';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import {
    LogOut,
    UserRound,
    Settings,
    ShieldCheck,
    FolderOpen,
    Bot,
    LockKeyhole,
    BookOpen,
    Code,
  } from '@lucide/svelte';
  import type { Auth } from '../svelte-lib/auth.svelte';
  let {
    auth,
    active,
    destination = '',
    onSignOut,
  }: {
    auth: Auth;
    active?: string;
    destination?: string;
    onSignOut: () => void;
  } = $props();
  const username = $derived(auth.account?.username ?? auth.user?.profile.preferred_username);
  const initials = $derived(
    auth.label
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'U',
  );
</script>

<DropdownMenu.Group>
  <DropdownMenu.GroupHeading class="product-menu-identity">
    <Avatar.Root class="size-7" aria-hidden="true"
      ><Avatar.Fallback class="text-xs">{initials}</Avatar.Fallback></Avatar.Root
    >
    <span
      ><strong>{auth.label}</strong><small>{username ? `@${username}` : 'Signed in'}</small></span
    >
  </DropdownMenu.GroupHeading>
  <DropdownMenu.Separator />
  {@render menuLink('/profile', 'Profile', active === 'profile')}
  {@render menuLink('/workspaces', 'Your workspaces', active === 'workspaces')}
</DropdownMenu.Group>
<DropdownMenu.Separator />
<DropdownMenu.Group>
  <DropdownMenu.GroupHeading>Account</DropdownMenu.GroupHeading>
  {@render menuLink(
    '/settings',
    'Settings',
    active === 'settings' && destination !== '/settings/security',
  )}
  {@render menuLink('/settings/security', 'Security', destination === '/settings/security')}
</DropdownMenu.Group>
<DropdownMenu.Separator />
<DropdownMenu.Group>
  <DropdownMenu.GroupHeading>Resources</DropdownMenu.GroupHeading>
  {@render menuLink('/docs/getting-started/', 'Getting started')}
  {@render menuLink('/moderation', 'Moderation', active === 'moderation')}
</DropdownMenu.Group>
<DropdownMenu.Separator />
<DropdownMenu.Item class="product-menu-item min-h-9 gap-2 px-2 cursor-pointer" onSelect={onSignOut}>
  <LogOut size={15} aria-hidden="true" /> Sign out
</DropdownMenu.Item>

{#snippet menuLink(href: string, label: string, current = false)}
  <DropdownMenu.Item class="product-menu-item min-h-9 gap-2 px-2 cursor-pointer">
    {#snippet child({ props })}
      <a
        {...props}
        {href}
        data-sveltekit-reload={href.startsWith('/docs') ? true : undefined}
        aria-current={current ? 'page' : undefined}
        >{#if href === '/profile'}<UserRound
            aria-hidden="true"
          />{:else if href === '/settings'}<Settings
            aria-hidden="true"
          />{:else if href === '/moderation'}<ShieldCheck
            aria-hidden="true"
          />{:else if href === '/workspaces'}<FolderOpen
            aria-hidden="true"
          />{:else if href === '/agents'}<Bot
            aria-hidden="true"
          />{:else if href === '/settings/security'}<LockKeyhole
            aria-hidden="true"
          />{:else if href === '/docs/getting-started/'}<BookOpen
            aria-hidden="true"
          />{:else if href === '/docs/developers/'}<Code aria-hidden="true" />{/if}{label}</a
      >
    {/snippet}
  </DropdownMenu.Item>
{/snippet}
