import { plainFileEditor } from '../helpers/project-editor';
import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';

test('local service supports accounts, research, Library copies, activity and uploads', async ({
  page,
  request,
  baseURL,
}) => {
  test.skip(!baseURL, 'Run through the local-mode smoke runner.');
  const username = `local${Date.now()}`;
  const password = 'local-browser-test-password';
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  const headers = { Origin: baseURL!, 'Idempotency-Key': `project-${username}` };
  const projectResponse = await page.request.post('/api/v1/projects', {
    headers,
    data: { name: 'Local browser research', visibility: 'PUBLIC' },
  });
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json();
  const snapshot = {
    kind: 'STATEMENT',
    content: {
      title: 'Persistent browser claim',
      content_md: 'A **local** statement with $x^2$.',
      assumptions_md: 'None stated',
      reported_outcome: null,
      explanation_md: null,
    },
    structural_relationships: [],
    change_summary: 'Browser smoke test',
  };
  const record = await page.request.post('/api/v1/objects', {
    headers,
    data: {
      destination: { kind: 'project', project_id: project.id },
      snapshot,
    },
  });
  expect(record.status(), await record.text()).toBe(201);
  const receipt = await record.json();
  const outputs = receipt.outputs as { entity_type: string; entity_id: string }[];
  const object = {
    id: outputs.find((output) => output.entity_type === 'RESEARCH_OBJECT')!.entity_id,
    object_version_id: outputs.find((output) => output.entity_type === 'OBJECT_VERSION')!.entity_id,
  };
  await page.goto(`/projects/${project.id}/objects/${object.id}`);
  await expect(
    page.getByRole('heading', { name: 'Persistent browser claim', exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator('.katex').first()).toBeVisible();
  const edit = await page.request.post(`/api/v1/objects/${object.id}/versions`, {
    headers,
    data: {
      expected_current_object_version_id: object.object_version_id,
      snapshot: {
        ...snapshot,
        content: {
          ...snapshot.content,
          title: 'Edited browser claim',
          content_md: 'An edited local statement.',
        },
      },
    },
  });
  expect(edit.status(), await edit.text()).toBe(201);
  const current = await (await page.request.get(`/api/v1/objects/${object.id}`)).json();
  const bytes = Buffer.from('Local browser evidence');
  const upload = await page.request.post(
    `/api/v1/artifacts?project_id=${project.id}&sha256=${createHash('sha256').update(bytes).digest('hex')}&byte_length=${bytes.length}`,
    { headers, data: bytes },
  );
  expect(upload.status()).toBe(201);
  const artifact = await upload.json();
  const attach = await page.request.post('/api/v1/attachments', {
    headers,
    data: {
      artifact_id: artifact.id,
      object_version_id: current.current_object_version_id,
      role: 'EVIDENCE',
    },
  });
  expect(attach.status()).toBe(200);
  const download = await page.request.get(`/api/v1/artifacts/${artifact.id}/content`);
  expect(await download.body()).toEqual(bytes);
  const admission = await page.request.post('/api/v1/catalogue', {
    headers,
    data: {
      kind: 'STATEMENT',
      title: 'Library browser claim',
      content_md: 'A sourced statement.',
      assumptions_md: 'Positive integers.',
      reported_status: 'Open',
      review_rationale: 'Local browser review.',
      reason: 'Exercise local Library',
    },
  });
  expect(admission.status()).toBe(201);
  const entry = await admission.json();
  const copy = await page.request.post('/api/v1/project-copies', {
    headers,
    data: { project_id: project.id, source_object_version_id: entry.object_version_id },
  });
  expect(copy.status()).toBe(201);
  expect((await copy.json()).object_id).not.toBe(entry.entry_id);
  await page.goto('/activity');
  await expect(page.getByText('Edited browser claim', { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText('Edited browser claim', { exact: true }).first()).toBeVisible();
  // A separate cookie jar cannot read an unattached staging artifact.
  const staging = await page.request.post(
    `/api/v1/artifacts?project_id=${project.id}&sha256=${createHash('sha256').update(bytes).digest('hex')}&byte_length=${bytes.length}`,
    { headers: { ...headers, 'Idempotency-Key': `staging-${username}` }, data: bytes },
  );
  const staged = await staging.json();
  expect((await request.get(`/api/v1/artifacts/${staged.id}/content`)).status()).toBe(404);
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
  await page.getByRole('button', { name: 'Create worktree', exact: true }).click();
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
  await page.screenshot({ path: '/private/tmp/native-worktrees-desktop.png', fullPage: true });
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
  await page.screenshot({ path: '/private/tmp/native-worktrees-mobile.png', fullPage: true });
  await drawer.getByRole('button', { name: 'Close drawer' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Saved, uncommitted notes');
});
