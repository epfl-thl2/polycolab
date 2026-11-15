import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type BrowserContext } from '@playwright/test';
import type { components } from '../../../src/web/src/lib/api-client';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const providerUrl = process.env.POLYCOLAB_INTEGRATION_PROVIDER_URL ?? 'http://127.0.0.1:18080';
const auth = (user: string) => ({ Authorization: `Bearer ${user}` });
async function call(
  request: APIRequestContext,
  method: 'post' | 'get' | 'patch' | 'delete',
  path: string,
  user = 'owner',
  data?: unknown,
) {
  const response = await request[method](`${apiUrl}/api/v1${path}`, { headers: auth(user), data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.status() === 204 ? undefined : response.json();
}
async function browserUser(context: BrowserContext, user: string) {
  await context.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await context.route('**/auth/me', (route) =>
    route.fulfill({ json: { authenticated: true, username: user, display_name: user } }),
  );
  // Only add authentication; all application responses come from the real API.
  await context.route(`${apiUrl}/api/v1/**`, (route) =>
    route.continue({ headers: { ...route.request().headers(), ...auth(user) } }),
  );
}

test('unified sessions persist shared browser participation and fence concurrent cancellation', async ({
  browser,
  request,
}) => {
  test.setTimeout(90_000);
  const owner = await browser.newContext();
  const contributor = await browser.newContext();
  const reader = await browser.newContext();
  try {
    const project = await call(request, 'post', '/projects', 'owner', {
      name: `Shared sessions ${randomUUID()}`,
      visibility: 'PRIVATE',
    });
    for (const [user, role] of [
      ['contributor', 'EDITOR'],
      ['reader', 'VIEWER'],
    ]) {
      const account = await call(request, 'get', '/account', user);
      await call(request, 'post', `/projects/${project.id}/members`, 'owner', {
        user_id: account.id,
        role,
      });
    }
    const profiles: Record<string, string> = {};
    for (const user of ['owner', 'contributor']) {
      profiles[user] = (
        await call(request, 'post', '/account/provider-connections', user, {
          display_name: `${user} session provider`,
          model_id: 'integration-model',
          base_url: 'https://8.8.8.8/v1',
          api_key: `test-${user}-provider-key`,
        })
      ).id;
    }
    const heldProfile = await call(
      request,
      'post',
      '/account/provider-connections',
      'contributor',
      {
        display_name: 'Held contributor provider',
        model_id: 'integration-held',
        base_url: 'https://8.8.8.8/v1',
        api_key: 'test-held-provider-key',
      },
    );
    await browserUser(owner, 'owner');
    await browserUser(contributor, 'contributor');
    await browserUser(reader, 'reader');
    const ownerPage = await owner.newPage();
    await ownerPage.goto(`/projects/${project.id}/conversations/new`);
    await ownerPage.getByLabel('Message the agent').fill('Start our shared investigation.');
    await ownerPage.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(ownerPage).toHaveURL(/\/conversations\/[0-9a-f-]+$/);
    const conversationId = new URL(ownerPage.url()).pathname.split('/').at(-1)!;
    await expect(ownerPage.getByText('Project context is ready.', { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await ownerPage.reload();
    await expect(
      ownerPage.getByText('Start our shared investigation.', { exact: true }),
    ).toBeVisible();
    await ownerPage.getByRole('button', { name: 'Sharing', exact: true }).click();
    await ownerPage.getByLabel('Project access').selectOption('members_can_participate');
    await ownerPage.getByRole('button', { name: 'Save sharing', exact: true }).click();
    const contributorPage = await contributor.newPage();
    await contributorPage.goto(`/projects/${project.id}/conversations/${conversationId}`);
    await contributorPage.getByRole('tab', { name: 'Agent history', exact: true }).click();
    await contributorPage.getByLabel('AI provider').selectOption(profiles.contributor);
    await contributorPage
      .getByLabel('Message shared with project')
      .fill('Contribute with my own provider.');
    await contributorPage.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect
      .poll(
        async () =>
          (await call(request, 'get', `/conversations/${conversationId}/runs`, 'contributor')).at(
            -1,
          ).status,
        { timeout: 30_000 },
      )
      .toBe('COMPLETED');
    await contributorPage.reload();
    await expect(
      contributorPage.getByText('Contribute with my own provider.', { exact: true }),
    ).toBeVisible();
    const runs = (await call(
      request,
      'get',
      `/conversations/${conversationId}/runs`,
      'owner',
    )) as components['schemas']['RunRead'][];
    expect(runs).toHaveLength(2);
    expect(runs[0].requested_by_user_id).not.toBe(runs[1].requested_by_user_id);
    expect(runs[1].can_read_private_context).toBe(false);
    expect(
      (
        await request.get(`${apiUrl}/api/v1/runs/${runs[1].id}/context`, { headers: auth('owner') })
      ).status(),
    ).toBe(404);
    const readerPage = await reader.newPage();
    await readerPage.goto(`/projects/${project.id}/conversations/${conversationId}`);
    await expect(
      readerPage.getByText('Contribute with my own provider.', { exact: true }),
    ).toBeVisible();
    await expect(readerPage.getByRole('button', { name: 'Send message', exact: true })).toHaveCount(
      0,
    );
    await expect(readerPage.getByRole('button', { name: 'Sharing', exact: true })).toHaveCount(0);

    await request.post(`${providerUrl}/__test__/hold`);
    await contributorPage.getByRole('tab', { name: 'Agent history', exact: true }).click();
    await contributorPage.getByLabel('AI provider').selectOption(heldProfile.id);
    await contributorPage.getByLabel('Message shared with project').fill('Wait for cancellation.');
    await contributorPage.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect
      .poll(
        async () =>
          (await call(request, 'get', `/conversations/${conversationId}/runs`, 'owner')).at(-1)
            .status,
      )
      .toBe('RUNNING');
    const queued = await Promise.all(
      Array.from({ length: 2 }, (_, index) => {
        const user = index % 2 ? 'contributor' : 'owner';
        return call(request, 'post', `/conversations/${conversationId}/events`, user, {
          type: 'message',
          client_request_id: randomUUID(),
          content_md: `Concurrent contribution ${index}`,
          provider_connection_id: profiles[user],
        });
      }),
    );
    expect(new Set(queued.map((value) => value.item.sequence)).size).toBe(2);
    expect(new Set(queued.map((value) => value.run.queue_sequence)).size).toBe(2);
    const denied = await request.post(`${apiUrl}/api/v1/conversations/${conversationId}/events`, {
      headers: auth('contributor'),
      data: { type: 'interrupt', run_id: queued[0].run.id },
    });
    expect(denied.status()).toBe(403);
    for (const value of queued)
      await call(request, 'post', `/conversations/${conversationId}/events`, 'owner', {
        type: 'interrupt',
        run_id: value.run.id,
      });
    await contributorPage.getByText('Files and run history', { exact: true }).click();
    await contributorPage.getByRole('button', { name: 'Stop run 3', exact: true }).click();
    await request.post(`${providerUrl}/__test__/release`);
    await expect
      .poll(
        async () =>
          (await call(request, 'get', `/conversations/${conversationId}/runs`, 'owner')).filter(
            (value: { status: string }) =>
              ['RUNNING', 'CANCELLING', 'QUEUED', 'CLAIMED'].includes(value.status),
          ).length,
        { timeout: 30_000 },
      )
      .toBe(0);
    await ownerPage.reload();
    await ownerPage.getByRole('button', { name: 'Archive session', exact: true }).click();
    await expect(ownerPage.getByText('This session is archived.', { exact: true })).toBeVisible();
    const stream = await request.get(`${apiUrl}/api/v1/conversations/${conversationId}/stream`, {
      headers: auth('reader'),
    });
    expect(stream.status()).toBe(200);
    const cursors = (await stream.text())
      .split('\n')
      .filter((line) => line.startsWith('id: '))
      .map((line) => line.slice(4));
    expect(cursors.length).toBeGreaterThan(8);
    expect(new Set(cursors).size).toBe(cursors.length);
    const replay = await request.get(`${apiUrl}/api/v1/conversations/${conversationId}/stream`, {
      headers: { ...auth('reader'), 'Last-Event-ID': cursors[2] },
    });
    expect(
      (await replay.text())
        .split('\n')
        .filter((line) => line.startsWith('id: '))
        .map((line) => line.slice(4)),
    ).toEqual(cursors.slice(3));
    await call(request, 'patch', `/conversations/${conversationId}/sharing`, 'owner', {
      mode: 'private',
    });
    expect(
      (
        await request.get(`${apiUrl}/api/v1/conversations/${conversationId}/stream`, {
          headers: auth('reader'),
        })
      ).status(),
    ).toBe(404);
    expect(
      (
        await request.get(`${apiUrl}/api/v1/conversations/${conversationId}/items`, {
          headers: auth('reader'),
        })
      ).status(),
    ).toBe(404);
  } finally {
    await request.post(`${providerUrl}/__test__/release`);
    await Promise.all([owner.close(), contributor.close(), reader.close()]);
  }
});
