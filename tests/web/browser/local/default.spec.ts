import { plainFileEditor } from '../helpers/project-editor';
import { expect, test } from '@playwright/test';

test('Default projects save current server files without version history', async ({
  page,
  baseURL,
}) => {
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(`default${Date.now()}`);
  await page.getByLabel('Password', { exact: true }).fill('default-project-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('default-project-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Project name', { exact: true }).fill('Default files');
  await expect(
    dialog.getByRole('combobox').filter({ has: page.locator('option[value="default"]') }),
  ).toHaveValue('default');
  await dialog.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/sessions\/new/);
  const id = new URL(page.url()).pathname.split('/')[2];
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await expect(tools.getByRole('tab', { name: 'History', exact: true })).toHaveCount(0);
  await expect(page.getByRole('tablist', { name: 'Project tabs' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'New file', exact: true }).click();
  await page.getByLabel('File path', { exact: true }).fill('notes/ideas.md');
  await page.getByRole('button', { name: 'Create file', exact: true }).click();
  await plainFileEditor(page);
  await page.getByLabel('File contents', { exact: true }).fill('Current ideas');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: /^Saved$/ })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'ideas.md', exact: true }).click();
  await plainFileEditor(page);
  await expect(page.getByLabel('File contents', { exact: true })).toHaveValue('Current ideas');
  const root = `/api/v1/projects/${id}/files`;
  const headers = { Origin: baseURL! };
  const original = await (
    await page.request.post(root, { headers, data: { action: 'read', path: 'notes/ideas.md' } })
  ).json();
  await page.getByLabel('File contents', { exact: true }).fill('Unsaved local edit');
  await page.request.post(root, {
    headers,
    data: {
      action: 'write',
      path: original.path,
      expected_digest: original.digest,
      content: 'Newer server edit',
    },
  });
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'This file changed' })).toBeVisible();
  await expect(page.getByLabel('File contents', { exact: true })).toHaveValue('Unsaved local edit');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'File actions', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Reload / discard edits', exact: true }).click();
  await expect(page.getByLabel('File contents', { exact: true })).toHaveValue('Newer server edit');
  await page.getByRole('button', { name: 'File actions', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Rename file', exact: true }).click();
  await page.getByLabel('File path', { exact: true }).fill('notes/renamed.md');
  await page.getByLabel('File path', { exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: 'renamed.md', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'File actions', exact: true }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('menuitem', { name: 'Delete file', exact: true }).click();
  await expect(page).toHaveURL(/\/sessions\/new/);
  expect((await (await page.request.get(root)).json()).files).toEqual([]);
  const composer = page
    .getByRole('textbox', { name: 'Message the agent', exact: true })
    .filter({ visible: true });
  await composer.fill('First draft');
  await page.getByRole('button', { name: 'Chats', exact: true }).click();
  await page.getByRole('button', { name: 'New chat', exact: true }).click();
  await composer.fill('Second draft');
  const conversations = page.getByRole('navigation', { name: 'Recent conversations' });
  await conversations.getByRole('link').first().click();
  await expect(composer).toHaveValue('First draft');
  await page.screenshot({ path: test.info().outputPath('default-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath('default-mobile.png') });
});
