import { plainFileEditor } from '../helpers/project-editor';
import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';

test('Default project files, delegated keys, artifacts, and retired routes use the real service', async ({
  page,
  request,
  baseURL,
}) => {
  test.skip(!baseURL, 'Run through the local-mode smoke runner.');
  const username = `local${Date.now()}`;
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill('local-browser-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('local-browser-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  const headers = { Origin: baseURL! };
  const response = await page.request.post('/api/v1/projects', {
    headers,
    data: {
      name: 'Shared filesystem',
      visibility: 'PUBLIC',
      workspace_mode: 'default',
    },
  });
  expect(response.status()).toBe(201);
  const project = await response.json();
  await page.goto(`/projects/${project.id}`);
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'New file', exact: true }).click();
  await page.getByLabel('File path', { exact: true }).fill('notes.txt');
  await page.getByRole('button', { name: 'Create file', exact: true }).click();
  await plainFileEditor(page);
  const editor = page.getByRole('textbox', { name: 'File contents', exact: true });
  await editor.fill('Saved by the human');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const root = `/api/v1/projects/${project.id}/files`;
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.post(root, { headers, data: { action: 'read', path: 'notes.txt' } })
          ).json()
        ).content,
    )
    .toBe('Saved by the human');
  await page.reload();
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'notes.txt', exact: true }).click();
  await plainFileEditor(page);
  await expect(editor).toHaveValue('Saved by the human');
  const identity = await (
    await page.request.post('/api/v1/account/agents', {
      headers,
      data: { name: 'Workspace helper' },
    })
  ).json();
  const key = await (
    await page.request.post('/api/v1/account/agent-keys', {
      headers,
      data: { name: 'File access', agent_id: identity.id },
    })
  ).json();
  const agentHeaders = { Authorization: `Bearer ${key.secret}` };
  const read = await request.post(root, {
    headers: agentHeaders,
    data: { action: 'read', path: 'notes.txt' },
  });
  expect(read.status()).toBe(200);
  const updated = await request.post(root, {
    headers: agentHeaders,
    data: {
      action: 'write',
      path: 'notes.txt',
      content: 'Updated by the agent',
      expected_digest: (await read.json()).digest,
    },
  });
  expect(updated.status()).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'Files', exact: true }).click();
  await page.getByRole('button', { name: 'notes.txt', exact: true }).click();
  await plainFileEditor(page);
  await expect(editor).toHaveValue('Updated by the agent');
  expect((await request.get(root)).status()).toBe(401);
  const bytes = Buffer.from('private project artifact');
  const artifactResponse = await page.request.post(`/api/v1/projects/${project.id}/artifacts`, {
    headers: { ...headers, 'Content-Type': 'application/octet-stream' },
    params: { sha256: createHash('sha256').update(bytes).digest('hex'), byte_length: bytes.length },
    data: bytes,
  });
  expect(artifactResponse.status()).toBe(201);
  const artifact = await artifactResponse.json();
  expect(artifact.state).toBe('COMMITTED');
  const download = `/api/v1/projects/${project.id}/artifacts/${artifact.id}/content`;
  expect(await (await page.request.get(download)).body()).toEqual(bytes);
  expect((await request.get(download)).status()).toBe(401);
  for (const path of [
    '/api/v1/objects',
    '/api/v1/catalogue',
    '/api/v1/research/records',
    '/api/v1/verification/jobs',
  ])
    expect((await request.get(path)).status()).toBe(404);
  await page.request.delete(`/api/v1/account/agent-keys/${key.id}`, { headers });
  expect((await request.get(root, { headers: agentHeaders })).status()).toBe(401);
});

test('native worktrees save without committing, retain drafts, and commit explicitly', async ({
  page,
  baseURL,
}) => {
  test.skip(!baseURL, 'Run through the local-mode smoke runner.');
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(`trees${Date.now()}`);
  await page.getByLabel('Password', { exact: true }).fill('local-browser-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('local-browser-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  const created = await page.request.post('/api/v1/projects', {
    headers: { Origin: baseURL! },
    data: { name: 'Native worktrees', visibility: 'PRIVATE' },
  });
  expect(created.status(), await created.text()).toBe(201);
  const project = await created.json();
  const root = `/api/v1/projects/${project.id}/worktrees`;
  await page.goto(`/projects/${project.id}/files`);
  await page.getByRole('button', { name: 'New worktree', exact: true }).click();
  await page.getByLabel('Worktree name', { exact: true }).fill('Experiment');
  await expect(page.getByLabel('Branch name', { exact: true })).toHaveValue('experiment');
  const worktreeCreated = page.waitForResponse(
    (response) => response.url().endsWith('/worktrees') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create worktree', exact: true }).click();
  expect((await worktreeCreated).status()).toBe(201);
  await expect(page.getByRole('button', { name: 'Select Experiment worktree' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await expect(page.getByRole('button', { name: 'Select Experiment worktree' })).toBeVisible();
  await page.getByRole('button', { name: 'New file', exact: true }).click();
  await page.getByLabel('File path', { exact: true }).fill('notes.md');
  await (await plainFileEditor(page)).fill('Saved, uncommitted notes');
  const trees = await (await page.request.get(root)).json();
  const tree = trees.find((item: { branch: string }) => item.branch === 'experiment');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Saved.', { exact: true })).toBeVisible();
  const saved = await (await page.request.get(`${root}/${tree.id}`)).json();
  expect(saved.head_commit).toBe(tree.head_commit);
  expect(saved.changed_files).toEqual([{ path: 'notes.md', status: 'added' }]);
  await (await plainFileEditor(page)).fill('Unsaved draft to retain');
  await page.getByRole('button', { name: 'Select Main worktree' }).click();
  await expect(page.getByRole('button', { name: 'Select Main worktree' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await page.getByRole('button', { name: 'Select Experiment worktree' }).click();
  await expect(page.getByRole('button', { name: 'Select Experiment worktree' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await expect(await plainFileEditor(page)).toHaveValue('Unsaved draft to retain');
  await page.getByRole('tab', { name: 'Source control', exact: true }).click();
  await page.getByRole('button', { name: 'Review & commit' }).click();
  await page.getByLabel('Commit message', { exact: true }).fill('Add notes');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Commit changes', exact: true }).click();
  await expect(page.getByText('Saved changes committed.', { exact: true })).toBeVisible();
  const committed = await (await page.request.get(`${root}/${tree.id}`)).json();
  expect(committed.head_commit).not.toBe(tree.head_commit);
  expect(committed.changed_files).toEqual([]);
  await page.screenshot({ path: '/tmp/native-worktrees-desktop.png', fullPage: true });
  await expect(await plainFileEditor(page)).toHaveValue('Unsaved draft to retain');
  page.once('dialog', (dialog) => dialog.accept());
  await page.reload();
  await page.getByRole('tab', { name: 'Explorer', exact: true }).click();
  await page.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Saved, uncommitted notes');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Hide left panel', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Worktrees', exact: true });
  await expect(drawer.getByRole('button', { name: 'Select Experiment worktree' })).toBeVisible();
  await page.screenshot({ path: '/tmp/native-worktrees-mobile.png', fullPage: true });
  await drawer.getByRole('button', { name: 'Close drawer' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Saved, uncommitted notes');
});
