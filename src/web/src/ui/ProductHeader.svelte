<script lang="ts">
  import BrandWordmark from './BrandWordmark.svelte';
  import PlannedBadge from './PlannedBadge.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { onMount, type Snippet } from 'svelte';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import * as Avatar from '../lib/components/ui/avatar';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import {
    LogOut,
    Menu,
    UserRound,
    Settings,
    Plug,
    ShieldCheck,
    ChevronDown,
    FolderOpen,
    Bot,
    LockKeyhole,
    BookOpen,
    Code,
    PanelLeft,
    PanelRight,
  } from '@lucide/svelte';
  import { accountHref } from '../lib/account-navigation';
  import type { Auth } from '../svelte-lib/auth.svelte';

  type Destination =
    | 'people'
    | 'agents'
    | 'chat'
    | 'search'
    | 'activity'
    | 'explore'
    | 'docs'
    | 'workspaces'
    | 'profile'
    | 'settings'
    | 'moderation';

  let {
    auth,
    active,
    projectName,
    projectVisibility,
    workspaceSidebarWidth,
    workspaceRightWidth,
    workspaceRightHandle = 0,
    workspacePanelMaximized = false,
    workspaceResizing = false,
    sidebarCollapsed = false,
    onToggleSidebar,
    onToggleRightPanel,
    workspaceSettingsHref,
    workspaceSettingsActive = false,
    workspaceAgentConnectHref,
    workspaceAgentConnectActive = false,
    children,
    currentPath,
  }: {
    children?: Snippet;
    auth: Auth;
    active?: Destination;
    projectName?: string;
    projectVisibility?: string;
    workspaceSidebarWidth?: number;
    workspaceRightWidth?: number;
    workspaceRightHandle?: number;
    workspacePanelMaximized?: boolean;
    workspaceResizing?: boolean;
    sidebarCollapsed?: boolean;
    onToggleSidebar?: () => void;
    onToggleRightPanel?: () => void;
    workspaceSettingsHref?: string;
    workspaceSettingsActive?: boolean;
    workspaceAgentConnectHref?: string;
    workspaceAgentConnectActive?: boolean;
    currentPath?: string;
  } = $props();

  let accountError = $state('');
  let interactive = $state(false);
  let initialPath = $state('/');
  let docsMenuOpen = $state(false);
  let docsMenuCloseTimer: ReturnType<typeof setTimeout> | undefined;
  onMount(() => {
    initialPath = location.pathname + location.search + location.hash;
    interactive = true;
    return () => clearTimeout(docsMenuCloseTimer);
  });
  const destination = $derived(currentPath ?? initialPath);
  const returnTo = $derived(destination === '/' ? '/workspaces' : destination);
  const username = $derived(auth.account?.username ?? auth.user?.profile.preferred_username);
  const workspaceMode = $derived(Boolean(projectName));
  const workspacesHref = $derived(auth.signedIn ? '/workspaces' : '/workspaces?scope=public');
  const initials = $derived(
    auth.label
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'U',
  );
  const mobileContext = $derived(
    projectName ??
      (active === 'people'
        ? 'People'
        : active === 'chat'
          ? 'Chat'
          : active === 'search'
            ? 'Home'
            : active === 'activity'
              ? 'Activity'
              : active === 'explore'
                ? 'Library'
                : active === 'docs'
                  ? 'Docs'
                  : active === 'agents'
                    ? 'Agent connections'
                    : active === 'settings'
                      ? 'Settings'
                      : active === 'profile'
                        ? 'Profile'
                        : active === 'moderation'
                          ? 'Moderation'
                          : active === 'workspaces'
                            ? 'Workspaces'
                            : 'Home'),
  );

  async function signOut() {
    accountError = '';
    try {
      await auth.signOut();
    } catch {
      accountError = 'Sign-out failed. Please retry.';
    }
  }

  function openDocsMenu() {
    clearTimeout(docsMenuCloseTimer);
    docsMenuOpen = true;
  }

  function closeDocsMenuSoon() {
    clearTimeout(docsMenuCloseTimer);
    docsMenuCloseTimer = setTimeout(() => {
      docsMenuOpen = false;
    }, 120);
  }
</script>

<header
  class="product-header"
  class:product-header-workspace={workspaceMode}
  class:product-header-workspace-collapsed={workspaceMode && sidebarCollapsed}
  class:product-header-workspace-resizing={workspaceMode && workspaceResizing}
  class:product-header-workspace-maximized={workspaceMode && workspacePanelMaximized}
>
  <div
    class="product-header-inner"
    class:product-header-inner-workspace={workspaceMode}
    class:product-header-with-search={Boolean(children)}
    style:--workspace-sidebar-width={workspaceSidebarWidth
      ? `${workspaceSidebarWidth}px`
      : undefined}
    style:--workspace-right-width={workspaceRightWidth !== undefined
      ? `${workspaceRightWidth}px`
      : undefined}
    style:--workspace-right-handle={`${workspaceRightHandle}px`}
  >
    <div class="product-header-brand" class:product-workspace-brand={workspaceMode}>
      <a
        class="product-brand"
        href="/"
        aria-label="Polycolab home"
        aria-describedby="product-development-status"
      >
        <span class="product-brand-mark" aria-hidden="true">
          <img src="/brand/polycolab-mark.png" alt="" />
        </span>
        <BrandWordmark descriptionId="product-development-status" />
      </a>
      {#if workspaceMode && onToggleSidebar}<Button
          type="button"
          variant="ghost"
          size="icon-sm"
          class="product-workspace-collapse"
          aria-label={sidebarCollapsed ? 'Expand left sidebar' : 'Collapse left sidebar'}
          title={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!sidebarCollapsed}
          onclick={onToggleSidebar}><PanelLeft class="size-4 shrink-0" aria-hidden="true" /></Button
        >{/if}
    </div>

    {#if workspaceMode}
      <nav class="product-breadcrumb" aria-label="Workspace breadcrumb">
        <a href={workspacesHref}>Workspaces</a><span aria-hidden="true">/</span>
        <strong>{projectName}</strong>
        {#if projectVisibility}<span class="product-visibility">{projectVisibility}</span>{/if}
        {#if onToggleRightPanel}<Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="product-workspace-expand-panel"
            aria-label="Expand panel"
            title="Expand panel"
            onclick={onToggleRightPanel}
            ><PanelRight class="size-4 shrink-0" aria-hidden="true" /></Button
          >{/if}
      </nav>
    {/if}

    <span class="product-mobile-context">{mobileContext}</span>

    {#if children}<div
        class="product-header-search"
        role="search"
        aria-label="Documentation search"
      >
        {@render children()}
      </div>{/if}

    {#if !workspaceMode}<nav class="product-navigation" aria-label="Main navigation">
        <a href="/library" aria-current={active === 'explore' ? 'page' : undefined}>Library</a>
        <a href={workspacesHref} aria-current={active === 'workspaces' ? 'page' : undefined}
          >Workspaces</a
        >
        <a href="/activity" aria-current={active === 'activity' ? 'page' : undefined}>Activity</a>
        <a href="/chat" aria-current={active === 'chat' ? 'page' : undefined}
          >Chat <PlannedBadge /></a
        >
        <div
          class="product-docs-menu"
          role="group"
          aria-label="Documentation"
          onpointerleave={closeDocsMenuSoon}
        >
          <a
            class="product-docs-link"
            href="/docs/"
            data-sveltekit-reload
            onpointerenter={openDocsMenu}
            aria-current={active === 'docs' ? 'page' : undefined}>Docs</a
          >
          <DropdownMenu.Root bind:open={docsMenuOpen}>
            <DropdownMenu.Trigger
              disabled={!interactive}
              class="product-docs-trigger"
              aria-label="Open Docs menu"
              ><ChevronDown size={14} aria-hidden="true" /></DropdownMenu.Trigger
            >
            <DropdownMenu.Content
              align="end"
              class="w-52"
              preventScroll={false}
              onpointerenter={openDocsMenu}
              onpointerleave={closeDocsMenuSoon}
            >
              {@render menuLink(
                '/docs/getting-started/',
                'Getting started',
                destination.startsWith('/docs/getting-started'),
              )}
              {@render menuLink(
                '/docs/developers/',
                'Developers',
                destination.startsWith('/docs/developers'),
              )}
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </nav>{/if}

    <div class="product-header-account">
      {#if workspaceMode && workspaceAgentConnectHref}<a
          class="product-workspace-settings"
          href={workspaceAgentConnectHref}
          title={sidebarCollapsed ? 'Agent connect' : undefined}
          aria-current={workspaceAgentConnectActive ? 'page' : undefined}
          ><Plug class="size-4 shrink-0" aria-hidden="true" /><span>Agent connect</span></a
        >{/if}
      {#if workspaceMode && workspaceSettingsHref}<a
          class="product-workspace-settings"
          href={workspaceSettingsHref}
          title={sidebarCollapsed ? 'Workspace settings' : undefined}
          aria-current={workspaceSettingsActive ? 'page' : undefined}
          ><Settings class="size-4 shrink-0" aria-hidden="true" /><span>Workspace settings</span></a
        >{/if}
      <div class="product-workspace-account-box">
        {#if !auth.loaded}
          <div class="product-account-loading" role="status" aria-label="Checking account">
            <span class="product-account-placeholder" aria-hidden="true"></span>
          </div>
        {:else if auth.signedIn}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger
              disabled={!interactive}
              class={buttonVariants({ variant: 'ghost', size: 'icon' }) +
                ' product-account-trigger'}
              aria-label={`Open account menu for ${auth.label}`}
            >
              <Avatar.Root class="size-7" aria-hidden="true"
                ><Avatar.Fallback class="text-xs">{initials}</Avatar.Fallback></Avatar.Root
              >
              {#if workspaceMode}<span class="product-workspace-account-label">{auth.label}</span
                >{/if}
            </DropdownMenu.Trigger>

            <DropdownMenu.Content
              class="w-60"
              side={workspaceMode ? 'top' : 'bottom'}
              sideOffset={8}
              align={workspaceMode ? 'start' : 'end'}
              preventScroll={false}
            >
              {@render accountMenu()}
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        {:else}
          <div class="product-auth-actions">
            {#if workspaceMode}
              <Button
                href={accountHref('signin', returnTo)}
                variant="ghost"
                size="lg"
                aria-label="Sign in"
                ><UserRound class="size-4 shrink-0" aria-hidden="true" /><span>Sign in</span
                ></Button
              >
              {#if !sidebarCollapsed}<Button href={accountHref('signup', returnTo)} size="lg"
                  >Create account</Button
                >{/if}
            {:else}
              <Button href={accountHref('signin', returnTo)} variant="ghost" size="lg"
                >Sign in</Button
              >
              <Button href={accountHref('signup', returnTo)} size="lg">Create account</Button>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    <div class="product-mobile-menu">
      <DropdownMenu.Root>
        <DropdownMenu.Trigger
          disabled={!interactive}
          class={buttonVariants({ variant: 'ghost', size: 'icon' }) +
            ' product-mobile-menu-trigger'}
          aria-label="Open navigation and account menu"
        >
          <Menu size={18} aria-hidden="true" />
        </DropdownMenu.Trigger>

        <DropdownMenu.Content
          class="w-60 product-mobile-menu-content"
          sideOffset={8}
          align="end"
          preventScroll={false}
        >
          <DropdownMenu.Group>
            <DropdownMenu.GroupHeading class="product-menu-heading"
              >Navigate</DropdownMenu.GroupHeading
            >
            {@render menuLink('/library', 'Library', active === 'explore')}
            {@render menuLink(workspacesHref, 'Workspaces', active === 'workspaces')}
            {@render menuLink('/activity', 'Activity', active === 'activity')}
            {@render menuLink('/chat', 'Chat', active === 'chat')}
            <DropdownMenu.Separator />
            <DropdownMenu.GroupHeading>Docs</DropdownMenu.GroupHeading>
            {@render menuLink('/docs/', 'Docs', active === 'docs')}
            {@render menuLink('/docs/getting-started/', 'Getting started')}
            {@render menuLink('/docs/developers/', 'Developers')}
          </DropdownMenu.Group>
          {#if !auth.loaded}
            <DropdownMenu.Separator />
            <DropdownMenu.Group>
              <DropdownMenu.GroupHeading class="product-menu-loading"
                >Checking account…</DropdownMenu.GroupHeading
              >
            </DropdownMenu.Group>
          {:else if auth.signedIn}
            <DropdownMenu.Separator />
            {@render accountMenu()}
          {:else}
            <DropdownMenu.Separator />
            {@render menuLink(accountHref('signin', returnTo), 'Sign in')}
            {@render menuLink(accountHref('signup', returnTo), 'Create account')}
          {/if}
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
  </div>
</header>
{#if accountError}<Alert.Root variant="destructive" role="alert" class="notice product-header-alert"
    >{accountError}</Alert.Root
  >{/if}

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
          />{:else if href === '/docs/developers/'}<Code
            aria-hidden="true"
          />{/if}{label}{#if href === '/chat'}
          <PlannedBadge />{/if}</a
      >
    {/snippet}
  </DropdownMenu.Item>
{/snippet}

{#snippet accountMenu()}
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
  <DropdownMenu.Item
    class="product-menu-item min-h-9 gap-2 px-2 cursor-pointer"
    onSelect={() => void signOut()}
  >
    <LogOut size={15} aria-hidden="true" /> Sign out
  </DropdownMenu.Item>
{/snippet}
