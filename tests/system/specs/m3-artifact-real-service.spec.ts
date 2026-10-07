import { createHash } from 'node:crypto';
import { expect, test, type APIRequestContext, type Download, type Page } from '@playwright/test';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const webUrl = process.env.POLYCOLAB_INTEGRATION_WEB_URL ?? 'http://127.0.0.1:13000';
const artifactsEnabled = process.env.POLYCOLAB_INTEGRATION_ARTIFACTS === '1';
const human = { Authorization: 'Bearer owner' };

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${apiUrl}${path}`, {
    headers: { ...human, 'Idempotency-Key': crypto.randomUUID() },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function uploadAndAttach(
  request: APIRequestContext,
  projectId: string,
  revisionId: string,
  bytes: Buffer,
) {
  const upload = await request.post(`${apiUrl}/api/v1/workspaces/${projectId}/artifacts`, {
    headers: { ...human, 'Content-Type': 'application/octet-stream' },
    params: {
      sha256: createHash('sha256').update(bytes).digest('hex'),
      byte_length: String(bytes.length),
      media_type: 'text/plain',
      source_revision_id: revisionId,
    },
    data: bytes,
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const artifact = await upload.json();
  const attachment = await request.post(`${apiUrl}/api/v1/attachments`, {
    headers: human,
    data: { artifact_id: artifact.id, revision_id: revisionId, role: 'EVIDENCE' },
  });
  expect(attachment.ok(), await attachment.text()).toBeTruthy();
  return artifact;
}

async function downloadBytes(download: Download) {
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
}

async function authenticate(page: Page) {
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'owner', display_name: 'M3 Owner' },
    }),
  );
  await page.route('**/api/v1/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), ...human } }),
  );
}

test('M3 real artifact bytes remain exact, authorized and selectively published', async ({
  page,
  browser,
}) => {
  test.skip(
    !artifactsEnabled,
    'Requires the platform-owned PostgreSQL/API/Garage harness with artifact UI enabled.',
  );
  test.setTimeout(90_000);
  await authenticate(page);

  const project = await post(page.request, '/api/v1/workspaces', {
    name: 'M3 artifact workspace',
  });
  const projectId = project.id as string;
  const record = await post(page.request, '/api/v1/records', {
    workspace_id: projectId,
    kind: 'COMPUTATION',
    title: 'Exact artifact-backed computation',
    content_md: 'Inspect the retained evidence bytes.',
    assumptions_md: 'No mathematical conclusion is implied.',
    statement_revision_ids: [],
    reported_outcome: 'PARTIAL',
    reason: 'Create artifact acceptance target',
  });
  const bytes = Buffer.from('<script>artifact bytes stay inert</script>\nresult=42');
  const privateBytes = Buffer.from('unselected private artifact');
  const unselected = await uploadAndAttach(
    page.request,
    projectId,
    record.revision_id,
    privateBytes,
  );

  await page.goto(`/projects/${projectId}/records/${record.revision_id}`);
  await expect(
    page.getByRole('heading', { name: 'Exact artifact-backed computation', level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Artifacts' })).toBeVisible();
  const uploadForm = page.locator('form').filter({
    has: page.getByRole('heading', { name: 'Upload artifact', level: 3 }),
  });
  await uploadForm.getByLabel('File').setInputFiles({
    name: 'hostile.html',
    mimeType: 'text/html',
    buffer: bytes,
  });
  await uploadForm.locator('select[required]').selectOption(record.revision_id);
  const uploadedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === `/api/v1/workspaces/${projectId}/artifacts`,
  );
  await page.getByRole('button', { name: 'Upload and verify artifact' }).click();
  const uploaded = await (await uploadedResponse).json();
  await expect(page.getByRole('region', { name: 'Artifacts' }).getByRole('status')).toContainText(
    'exact attachment committed',
  );

  const artifact = page.getByRole('article', { name: `Artifact ${uploaded.id}` });
  await expect(artifact).toContainText(
    `sha256:${createHash('sha256').update(bytes).digest('hex')}`,
  );
  await expect(artifact).toContainText(`${bytes.length} bytes`);
  await expect(artifact).toContainText('text/html');
  await expect(artifact).toContainText(record.revision_id);
  await expect(artifact.locator('script')).toHaveCount(0);

  const privateDownload = page.waitForEvent('download');
  await artifact.getByRole('button', { name: 'Download artifact as data' }).click();
  const downloaded = await privateDownload;
  expect(downloaded.suggestedFilename()).toBe(`artifact-${uploaded.id}`);
  expect(await downloadBytes(downloaded)).toEqual(bytes);

  const selection = page.getByRole('group', { name: 'Exact publication selection' });
  await selection.getByRole('checkbox', { name: /Exact artifact-backed computation/ }).check();
  await selection.getByText(`Artifact ${uploaded.id}`, { exact: true }).click();
  await expect(
    selection.getByRole('checkbox', { name: new RegExp(`Artifact ${uploaded.id}`) }),
  ).toBeChecked();
  await page.getByRole('button', { name: 'Request exact preview' }).click();
  const preview = page.getByRole('region', { name: 'Exact sanitized public preview' });
  await expect(preview).toContainText(`Artifact ${uploaded.id}`);
  await expect(preview).toContainText(`sha256:${uploaded.sha256}`);
  await expect(preview).not.toContainText('artifact bytes stay inert');
  await preview.getByRole('checkbox', { name: /I reviewed this exact server/ }).check();
  await preview.getByLabel('Publication reason').fill('Release exact verified artifact bytes.');
  await preview.getByRole('button', { name: 'Confirm exact publication' }).click();
  const release = page.getByRole('link', { name: /Open immutable public release/ });
  await expect(release).toBeVisible();
  const publicHref = await release.getAttribute('href');
  expect(publicHref).toMatch(/^\/commons\/publications\//);

  const anonymous = await browser.newContext({ acceptDownloads: true });
  try {
    const denied = await anonymous.request.get(`${apiUrl}/api/v1/artifacts/${uploaded.id}/content`);
    expect(denied.status()).toBe(401);
    const hidden = await anonymous.request.get(
      `${apiUrl}/api/v1/artifacts/${unselected.id}/content`,
    );
    expect(hidden.status()).toBe(404);

    const publicPage = await anonymous.newPage();
    await publicPage.goto(`${webUrl}${publicHref}`);
    const releasedArtifacts = publicPage.getByRole('region', { name: 'Released artifacts' });
    await expect(releasedArtifacts).toBeVisible();
    await expect(releasedArtifacts.locator('script')).toHaveCount(0);
    await expect(releasedArtifacts).not.toContainText('artifact bytes stay inert');
    const publicDownload = publicPage.waitForEvent('download');
    await publicPage
      .getByRole('link', { name: `Download artifact ${uploaded.id} as data` })
      .click();
    expect(await downloadBytes(await publicDownload)).toEqual(bytes);

    const publicResponse = await anonymous.request.get(
      `${apiUrl}/api/v1/artifacts/${uploaded.id}/content`,
    );
    expect(publicResponse.status()).toBe(200);
    expect(await publicResponse.body()).toEqual(bytes);
    expect(publicResponse.headers()['content-type']).toContain('application/octet-stream');
    expect(publicResponse.headers()['x-content-type-options']).toBe('nosniff');
    expect(publicResponse.headers()['cache-control']).toBe('no-store');
  } finally {
    await anonymous.close();
  }
});
