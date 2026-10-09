import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';

import AccountSettings from '../../../src/web/src/ui/AccountSettings.svelte';
import Administration from '../../../src/web/src/ui/Administration.svelte';
import Profile from '../../../src/web/src/ui/Profile.svelte';
import { Auth } from '../../../src/web/src/svelte-lib/auth.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';

afterEach(cleanup);

function context(
  search = vi.fn().mockResolvedValue({
    items: [],
    next_cursor: null,
  }),
) {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: true, username: 'ada', display_name: 'Ada Lovelace' };
  auth.loaded = true;
  return new Map([
    [
      contextKey,
      {
        auth,
        catalogue: { search },
        externalAgents: { identity: vi.fn().mockResolvedValue({ user_id: 'user-ada' }) },
        history: {
          profile: vi.fn().mockResolvedValue({
            actor: { kind: 'human', user_id: 'user-ada', display_name: 'Ada Lovelace' },
            authored_contributions: 2,
            sponsored_contributions: 0,
          }),
          activity: search,
        },
      },
    ],
  ]);
}

it('loads public profile activity by stable user ID and separates sponsorship', async () => {
  const activity = vi.fn().mockResolvedValue({
    items: [
      {
        id: 'event-1',
        contribution_id: 'contribution-1',
        action: 'object.created',
        actor: { kind: 'human', user_id: 'user-ada', display_name: 'Ada Lovelace' },
        object_id: 'object-1',
        revision_id: 'revision-1',
        title: 'A constructive compactness proof',
        object_kind: 'PROOF',
        occurred_at: '2026-09-08T10:00:00Z',
        workspace_id: null,
      },
    ],
    next_cursor: null,
  });
  render(Profile, { context: context(activity) });
  expect(await screen.findByRole('heading', { name: 'Ada Lovelace' })).toBeTruthy();
  expect(await screen.findByText('A constructive compactness proof')).toBeTruthy();
  expect(activity).toHaveBeenCalledWith('user-ada', false, undefined, 'all');
  await fireEvent.click(screen.getByRole('button', { name: 'sponsored' }));
  await waitFor(() =>
    expect(activity).toHaveBeenCalledWith('user-ada', false, undefined, 'sponsored'),
  );
});

it('keeps loaded profile contributions when pagination fails and retries the same cursor', async () => {
  const search = vi
    .fn()
    .mockResolvedValueOnce({
      items: [
        {
          id: 'event-r1',
          revision_id: 'r1',
          object_id: 'object-r1',
          action: 'object.created',
          object_kind: 'STATEMENT',
          actor: { kind: 'human', user_id: 'user-ada', display_name: 'Ada Lovelace' },
          title: 'First contribution',
          occurred_at: '2026-09-10T10:00:00Z',
          workspace_id: null,
        },
      ],
      next_cursor: 'page-2',
    })
    .mockRejectedValueOnce(new Error('Offline'))
    .mockResolvedValueOnce({ items: [], next_cursor: null });
  render(Profile, { context: context(search) });
  await screen.findByRole('link', { name: 'First contribution' });
  await fireEvent.click(screen.getByRole('button', { name: 'Load more contributions' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Could not load contributions');
  expect(screen.getByRole('link', { name: 'First contribution' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(search).toHaveBeenLastCalledWith('user-ada', false, 'page-2', 'all'));
  expect(screen.getByRole('link', { name: 'First contribution' })).toBeTruthy();
});

it('keeps the researcher profile free of personal management shortcuts', () => {
  render(Profile, { context: context() });

  expect(screen.queryByRole('button', { name: 'Edit profile' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Complete profile' })).toBeNull();
  expect(screen.queryByRole('heading', { name: 'Edit profile preview' })).toBeNull();
  for (const name of ['Manage account', 'Your workspaces', 'Agent connections']) {
    expect(screen.queryByRole('link', { name })).toBeNull();
  }
  expect(screen.queryByRole('link', { name: 'View your activity' })).toBeNull();
});

it('does not show zero contribution totals before a successful load', async () => {
  const search = vi.fn().mockRejectedValue(new Error('Offline'));
  render(Profile, { context: context(search) });
  expect(screen.getByLabelText('Contribution count unavailable').textContent).toBe('—');
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Contribution count unavailable').textContent).toBe('—');
  expect(screen.queryByText('No public contributions loaded')).toBeNull();
  expect(screen.getByText('Contribution history unavailable')).toBeTruthy();
  expect(screen.queryByRole('region', { name: /Yearly contribution calendar/ })).toBeNull();
});

it('shows core settings without capability configuration', () => {
  render(AccountSettings, { props: { path: '/settings' }, context: context() });

  expect(screen.getByRole('heading', { name: 'Profile' })).toBeTruthy();
  const navigation = screen.getByRole('navigation', { name: 'Settings sections' });
  for (const item of ['Profile', 'Security', 'API keys', 'Builtin agents'])
    expect(within(navigation).getByRole('link', { name: item })).toBeTruthy();
  for (const item of ['Account recovery'])
    expect(within(navigation).queryByRole('link', { name: item })).toBeNull();
  expect(screen.getByText('Ada Lovelace')).toBeTruthy();
  expect(screen.getByText('ada', { exact: true })).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'View profile' })).toBeNull();
  expect(screen.queryByText('Sign-in method')).toBeNull();
  expect(within(navigation).queryByRole('link', { name: 'Notifications' })).toBeNull();
  expect(
    within(navigation).getByRole('link', { name: 'Profile' }).getAttribute('aria-current'),
  ).toBe('page');
});

it('shows a disabled password reset option when email recovery is unavailable', () => {
  render(AccountSettings, { props: { path: '/settings/security' }, context: context() });
  expect(
    (screen.getByRole('button', { name: 'Reset password' }) as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(screen.getByText(/Password reset is unavailable/)).toBeTruthy();
});

it('links password reset to the implemented recovery flow when enabled', () => {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  render(AccountSettings, {
    props: { path: '/settings/security' },
    context: new Map([[contextKey, { auth, capabilities: { enabled: () => true } }]]),
  });
  expect(screen.getByRole('link', { name: 'Reset password' }).getAttribute('href')).toBe(
    '/forgot-password',
  );
});

it('groups external keys and built-in providers under agent settings', () => {
  const auth = new Auth(() => {});
  render(AccountSettings, {
    props: { path: '/settings' },
    context: new Map([[contextKey, { auth, capabilities: { enabled: () => true } }]]),
  });
  const group = screen.getByRole('group', { name: 'Agent settings' });
  expect(within(group).getByRole('link', { name: 'API keys' }).getAttribute('href')).toBe(
    '/settings/agent-keys',
  );
  expect(within(group).getByRole('link', { name: 'Builtin agents' }).getAttribute('href')).toBe(
    '/settings/providers',
  );
});

it('presents administration as a future deployment-level surface', () => {
  render(Administration);

  expect(screen.getByRole('heading', { name: 'Administration' })).toBeTruthy();
  expect(screen.getByText('People & access', { exact: true })).toBeTruthy();
  expect(screen.getByText('Agents & execution', { exact: true })).toBeTruthy();
  expect(screen.getByText('System health', { exact: true })).toBeTruthy();
});

it('creates an account-wide key without a workspace and forgets its secret on navigation', async () => {
  const auth = new Auth(() => {});
  auth.configuration = { mode: 'local' };
  auth.account = { authenticated: true, username: 'ada', display_name: 'Ada' };
  auth.loaded = true;
  const externalAgents = {
    identity: vi.fn().mockResolvedValue({
      kind: 'human',
      agent_key_policy: {
        scope: 'ACCOUNT',
        ttl_seconds: 2592000,
        max_requests: 10000,
        max_mutations: 1000,
      },
    }),
    listAgents: vi.fn().mockResolvedValue({ items: [], nextCursor: undefined }),
    createAgent: vi.fn().mockResolvedValue({ id: 'agent-1' }),
    listCredentials: vi.fn().mockResolvedValue({ items: [], nextCursor: undefined }),
    createCredential: vi.fn().mockResolvedValue({ id: 'key-1', secret: 'one-time-test-secret' }),
  };
  const view = render(AccountSettings, {
    props: { path: '/settings/agent-keys' },
    context: new Map([
      [contextKey, { auth, externalAgents, capabilities: { enabled: () => true } }],
    ]),
  });
  await waitFor(() =>
    expect(
      (screen.getByRole('button', { name: 'New API key' }) as HTMLButtonElement).disabled,
    ).toBe(false),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'New API key' }));
  await waitFor(() => expect(screen.getByText(/Expires after 30 days/)).toBeTruthy());
  expect(
    screen.getByText(/including private workspaces and workspaces you join later/),
  ).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Polycolab agent name' })).toBeNull();
  await fireEvent.input(screen.getByLabelText('Polycolab agent name'), {
    target: { value: 'Ada assistant' },
  });
  await fireEvent.input(screen.getByLabelText('Key name'), { target: { value: 'My assistant' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }));
  await waitFor(() =>
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe(
      'one-time-test-secret',
    ),
  );
  expect(externalAgents.createCredential).toHaveBeenCalledWith(
    'My assistant',
    'agent-1',
    false,
    false,
  );
  await view.rerender({ path: '/settings/security' });
  expect(screen.queryByLabelText('API key')).toBeNull();
  await view.rerender({ path: '/settings/agent-keys' });
  await waitFor(() => expect(screen.getByRole('heading', { name: 'API keys' })).toBeTruthy());
  expect(screen.queryByLabelText('API key')).toBeNull();
});

it('keeps model providers accessible when agent execution is unavailable', () => {
  render(AccountSettings, { props: { path: '/settings/providers' }, context: context() });
  expect(screen.getByRole('heading', { name: 'Builtin agents' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Built-in agents are unavailable' })).toBeTruthy();
  expect(
    (screen.getByRole('button', { name: 'Add model provider' }) as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(screen.getByRole('link', { name: 'Builtin agents' }).getAttribute('aria-current')).toBe(
    'page',
  );
});

it('separates existing agent selection from creating a new agent', async () => {
  const auth = new Auth(() => {});
  const externalAgents = {
    identity: vi.fn().mockResolvedValue({
      agent_key_policy: { ttl_seconds: 86400, max_requests: 100, max_mutations: 10 },
    }),
    listAgents: vi
      .fn()
      .mockResolvedValue({ items: [{ id: 'existing-agent', name: 'Proof helper' }] }),
    listCredentials: vi.fn().mockResolvedValue({ items: [] }),
    createAgent: vi.fn(),
    createCredential: vi.fn().mockResolvedValue({ id: 'key-existing', secret: 'test-only-secret' }),
  };
  render(AccountSettings, {
    props: { path: '/settings/agent-keys' },
    context: new Map([[contextKey, { auth, externalAgents }]]),
  });
  const trigger = screen.getByRole('button', { name: 'New API key' }) as HTMLButtonElement;
  await waitFor(() => expect(trigger.disabled).toBe(false));
  await fireEvent.click(trigger);
  expect(
    (screen.getByRole('combobox', { name: 'Polycolab agent name' }) as HTMLSelectElement).value,
  ).toBe('existing-agent');
  expect(screen.queryByRole('textbox', { name: 'Polycolab agent name' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Create new agent' }));
  expect(screen.getByRole('textbox', { name: 'Polycolab agent name' })).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Polycolab agent name' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Use an existing agent' }));
  await fireEvent.input(screen.getByLabelText('Key name'), {
    target: { value: 'Replacement key' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }));
  await waitFor(() =>
    expect(externalAgents.createCredential).toHaveBeenCalledWith(
      'Replacement key',
      'existing-agent',
      false,
      false,
    ),
  );
  expect(externalAgents.createAgent).not.toHaveBeenCalled();
});
