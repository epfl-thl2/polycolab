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
  await expect(page).toHaveURL(/\/workspaces$/);
  const headers = { Origin: baseURL!, 'Idempotency-Key': `workspace-${username}` };
  const workspace = await page.request.post('/api/v1/workspaces', {
    headers,
    data: { name: 'Local browser research', visibility: 'PUBLIC' },
  });
  expect(workspace.status()).toBe(201);
  const project = await workspace.json();
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
      destination: { kind: 'workspace', workspace_id: project.id },
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
  await page.goto(`/workspaces/${project.id}/objects/${object.id}`);
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
    `/api/v1/artifacts?workspace_id=${project.id}&sha256=${createHash('sha256').update(bytes).digest('hex')}&byte_length=${bytes.length}`,
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
  const copy = await page.request.post('/api/v1/workspace-copies', {
    headers,
    data: { workspace_id: project.id, source_object_version_id: entry.object_version_id },
  });
  expect(copy.status()).toBe(201);
  expect((await copy.json()).object_id).not.toBe(entry.entry_id);
  await page.goto('/activity');
  await expect(page.getByText('Edited browser claim', { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText('Edited browser claim', { exact: true }).first()).toBeVisible();
  // A separate cookie jar cannot read an unattached staging artifact.
  const staging = await page.request.post(
    `/api/v1/artifacts?workspace_id=${project.id}&sha256=${createHash('sha256').update(bytes).digest('hex')}&byte_length=${bytes.length}`,
    { headers: { ...headers, 'Idempotency-Key': `staging-${username}` }, data: bytes },
  );
  const staged = await staging.json();
  expect((await request.get(`/api/v1/artifacts/${staged.id}/content`)).status()).toBe(404);
});
