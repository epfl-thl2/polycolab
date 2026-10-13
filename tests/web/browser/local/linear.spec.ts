import { expect, test, type Page } from '@playwright/test';

async function signup(page: Page, username: string) {
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill('collaboration-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('collaboration-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

test('linear coediting persists, reconnects, and restores across two real members', async ({
  page,
  browser,
  baseURL,
}) => {
  test.setTimeout(180_000);
  const peerContext = await browser.newContext({ baseURL });
  const peer = await peerContext.newPage();
  try {
    await signup(page, `linearowner${Date.now()}`);
    await signup(peer, `linearpeer${Date.now()}`);
    const member = await (await peer.request.get('/api/v1/users/me')).json();
    const headers = { Origin: baseURL! };
    const response = await page.request.post('/api/v1/projects', {
      headers,
      data: { name: 'Live collaboration', visibility: 'PRIVATE', workspace_mode: 'linear' },
    });
    expect(response.status()).toBe(201);
    const project = await response.json();
    expect(
      (
        await page.request.post(`/api/v1/projects/${project.id}/members`, {
          headers,
          data: { user_id: member.id, role: 'CONTRIBUTOR' },
        })
      ).status(),
    ).toBe(201);
    const path = `/projects/${project.id}/files`;
    await page.goto(path);
    await expect(page.getByRole('status').filter({ hasText: /^Saved/ })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole('textbox', { name: 'File path', exact: true }).fill('notes.txt');
    await page.getByRole('button', { name: 'New file', exact: true }).click();
    await page.getByRole('button', { name: 'notes.txt', exact: true }).dblclick();
    await page.getByRole('button', { name: 'Text editor', exact: true }).click();
    const editor = page.getByRole('textbox', { name: 'File contents', exact: true });
    await editor.fill('Shared text\n');
    await expect(page.getByRole('status').filter({ hasText: /^Saved/ })).toBeVisible();
    await peer.goto(path + '?file=notes.txt');
    await peer.getByRole('button', { name: 'Text editor', exact: true }).click();
    const peerEditor = peer.getByRole('textbox', { name: 'File contents', exact: true });
    await expect(peerEditor).toHaveValue('Shared text\n');
    await peerEditor.fill('Shared text\nPeer edit\n');
    await expect(editor).toHaveValue('Shared text\nPeer edit\n');
    await page.getByRole('button', { name: 'History', exact: true }).click();
    await page.getByRole('textbox', { name: 'Checkpoint name' }).fill('Together');
    await page.getByRole('button', { name: 'Create checkpoint', exact: true }).click();
    await expect(page.getByRole('button', { name: /^Together/ })).toBeVisible();
    await peerContext.setOffline(true);
    await expect(peerEditor).toBeDisabled();
    await peerContext.setOffline(false);
    await expect(peerEditor).toBeEnabled();
    await peerEditor.fill('Later edit\n');
    await expect(editor).toHaveValue('Later edit\n');
    await page.getByRole('button', { name: /^Together/ }).click();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Restore project', exact: true }).click();
    await expect(
      peer.getByRole('status').filter({ hasText: /project was restored/ }),
    ).toBeVisible();
    await page.goto(path + '?file=notes.txt');
    await page.getByRole('button', { name: 'Text editor', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'File contents', exact: true })).toHaveValue(
      'Shared text\nPeer edit\n',
    );
  } finally {
    await peerContext.close();
  }
});
