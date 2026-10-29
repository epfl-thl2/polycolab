import { plainFileEditor } from '../helpers/project-editor';
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
    await page.getByRole('button', { name: 'Files', exact: true }).click();
    await page.getByRole('button', { name: 'New file', exact: true }).click();
    await page.getByRole('textbox', { name: 'File path', exact: true }).fill('notes.txt');
    await page.getByRole('button', { name: 'Create file', exact: true }).click();
    await page.getByRole('button', { name: 'notes.txt', exact: true }).dblclick();
    await plainFileEditor(page);
    const editor = page.getByRole('textbox', { name: 'File contents', exact: true });
    await editor.fill('Shared text\n');
    await expect(page.getByRole('status').filter({ hasText: /^Saved/ })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('linear-desktop.png') });
    await test.info().attach('linear-desktop', {
      path: test.info().outputPath('linear-desktop.png'),
      contentType: 'image/png',
    });
    await peer.goto(path + '?file=notes.txt');
    await plainFileEditor(peer);
    const peerEditor = peer.getByRole('textbox', { name: 'File contents', exact: true });
    await expect(peerEditor).toHaveValue('Shared text\n');
    await peerEditor.fill('Shared text\nPeer edit\n');
    await expect(editor).toHaveValue('Shared text\nPeer edit\n');
    await page.getByRole('tab', { name: 'History', exact: true }).click();
    await page.getByRole('textbox', { name: 'Checkpoint name' }).fill('Together');
    await page.getByRole('button', { name: 'Create checkpoint', exact: true }).click();
    await expect(page.getByRole('button', { name: /^Together/ })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: /^(Show|Hide) tools$/ }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByRole('button', { name: /^Together/ })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('linear-mobile-history.png') });
    await test.info().attach('linear-mobile-history', {
      path: test.info().outputPath('linear-mobile-history.png'),
      contentType: 'image/png',
    });
    await drawer.getByRole('button', { name: 'Close drawer', exact: true }).click();
    await expect(drawer).toBeHidden();
    await page.setViewportSize({ width: 1280, height: 900 });
    await peerContext.setOffline(true);
    await expect(peerEditor).toBeDisabled();
    await peerContext.setOffline(false);
    await expect(peerEditor).toBeEnabled();
    await peerEditor.fill('Later edit\n');
    await page.getByRole('tab', { name: 'File', exact: true }).click();
    await expect(editor).toHaveValue('Later edit\n');
    await page.getByRole('tab', { name: 'History', exact: true }).click();
    await page.getByRole('button', { name: /^Together/ }).click();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Restore project', exact: true }).click();
    await expect(peer.getByRole('alert').filter({ hasText: /project was restored/ })).toBeVisible();
    await page.goto(path + '?file=notes.txt');
    await plainFileEditor(page);
    await expect(page.getByRole('textbox', { name: 'File contents', exact: true })).toHaveValue(
      'Shared text\nPeer edit\n',
    );

    await page.goto(`/projects/${project.id}`);
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/sessions/new`));
    await expect(page.getByRole('tablist', { name: 'Project tabs' })).toHaveCount(0);
    const conversations = page.getByRole('complementary', { name: 'Conversations', exact: true });
    await expect(conversations.getByText('AI file results', { exact: false })).toHaveCount(0);
    await expect(page.getByText('People here', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Collaborators online', { exact: false })).toHaveCount(0);
    await expect(conversations.getByText('Shared with you', { exact: true })).toHaveCount(0);
    const chat = page
      .getByRole('textbox', { name: 'Message the agent', exact: true })
      .filter({ visible: true });
    await chat.fill('Keep my conversation draft');
    const firstDraft = page.url();
    await conversations.getByRole('button', { name: 'New chat', exact: true }).click();
    await expect(chat).toHaveValue('');
    await chat.fill('Second conversation draft');
    await conversations.getByRole('link', { name: 'New chat Draft', exact: true }).first().click();
    await expect(page).toHaveURL(firstDraft);
    await expect(chat).toHaveValue('Keep my conversation draft');
    await page.getByRole('button', { name: 'Files', exact: true }).click();
    await page.getByRole('button', { name: 'notes.txt', exact: true }).click();
    await expect(page.getByRole('tab', { name: 'File', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await page.getByRole('button', { name: 'Chats', exact: true }).click();
    await expect(chat).toHaveValue('Keep my conversation draft');
    await page.screenshot({ path: test.info().outputPath('linear-chat-desktop.png') });
    await page.getByRole('tab', { name: 'Agent changes', exact: true }).click();
    await page.getByText('Agent file changes (0 to review)', { exact: true }).click();
    await expect(page.getByText('No agent file changes yet.', { exact: true })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: /^(Show|Hide) left panel$/ }).click();
    const chatDrawer = page.getByRole('dialog', { name: 'Conversations', exact: true });
    await expect(
      chatDrawer.getByRole('navigation', { name: 'Recent conversations', exact: true }),
    ).toBeVisible();
    await chatDrawer.getByRole('link', { name: 'New chat Draft', exact: true }).last().click();
    await expect(chatDrawer).toBeHidden();
    await expect(chat).toHaveValue('Second conversation draft');
    await page.screenshot({ path: test.info().outputPath('linear-chat-mobile.png') });
  } finally {
    await peerContext.close();
  }
});
