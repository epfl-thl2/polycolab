import { expect, test, type APIRequestContext } from '@playwright/test';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const webUrl = process.env.POLYCOLAB_INTEGRATION_WEB_URL ?? 'http://127.0.0.1:13000';
const human = { Authorization: 'Bearer owner' };

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${apiUrl}${path}`, {
    headers: { ...human, 'Idempotency-Key': crypto.randomUUID() },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function put(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.put(`${apiUrl}${path}`, {
    headers: { ...human, 'Idempotency-Key': crypto.randomUUID() },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test('M2 real publication preview matches anonymous immutable output', async ({
  page,
  browser,
}) => {
  test.setTimeout(90_000);
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'owner', display_name: 'M2 Owner' },
    }),
  );
  await page.route('**/api/v1/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), ...human } }),
  );
  const project = await post(page.request, '/api/v1/projects', {
    name: 'M2 publication project',
  });
  const projectId = project.id;
  const owner = await page.request.get(`${apiUrl}/api/v1/users/me`, { headers: human });
  expect(owner.ok(), await owner.text()).toBeTruthy();
  const ownerId = (await owner.json()).id as string;
  const successor = await page.request.get(`${apiUrl}/api/v1/users/me`, {
    headers: { Authorization: 'Bearer contributor' },
  });
  expect(successor.ok(), await successor.text()).toBeTruthy();
  const successorId = (await successor.json()).id as string;
  await post(page.request, `/api/v1/projects/${projectId}/members`, {
    user_id: successorId,
    role: 'OWNER',
  });

  const claim = await post(page.request, '/api/v1/records', {
    project_id: projectId,
    kind: 'CLAIM',
    title: 'Exact private claim',
    content_md: 'Every finite tree has a leaf.',
    assumptions_md: 'The tree is nonempty.',
    reported_outcome: 'UNASSESSED',
    reason: 'Create publication target',
  });
  const proof = await post(page.request, '/api/v1/records', {
    project_id: projectId,
    kind: 'PROOF_SKETCH',
    title: 'Exact private proof sketch',
    content_md: 'Choose a longest path and inspect an endpoint.',
    assumptions_md: 'Finite nonempty tree.',
    statement_revision_ids: [claim.revision_id],
    reported_outcome: 'PARTIAL',
    reason: 'Create exact proof sketch',
    proof_sketch: {
      conclusion_revision_id: claim.revision_id,
      premise_revision_ids: [],
      reported_progress: 'PARTIAL',
    },
  });
  const summary = await put(page.request, `/api/v1/research/objects/${proof.id}/summary`, {
    project_id: projectId,
    body_md: 'The endpoint argument proves the exact claim.',
    source_revision_ids: [proof.revision_id, claim.revision_id],
  });
  const comment = await post(page.request, `/api/v1/research/objects/${proof.id}/comments`, {
    project_id: projectId,
    revision_id: proof.revision_id,
    body_md: 'The maximal-path endpoint needs degree one.',
  });
  const progress = await post(page.request, `/api/v1/research/objects/${proof.id}/progress`, {
    project_id: projectId,
    revision_id: proof.revision_id,
    status: 'PARTIAL',
    detail_md: 'The dependency closure is ready for review.',
  });
  const privateMarker = `PRIVATE-NOTE-${crypto.randomUUID()}`;
  await put(page.request, `/api/v1/research/objects/${proof.id}/human-note`, {
    project_id: projectId,
    body_md: privateMarker,
  });

  await page.goto(`/projects/${projectId}/records/${proof.revision_id}`);
  await expect(
    page.getByRole('heading', { name: 'Exact private proof sketch', level: 1 }),
  ).toBeVisible();
  await page.getByRole('checkbox', { name: /Exact private proof sketch/ }).check();
  await page.getByRole('checkbox', { name: /Authored summary revision/ }).check();
  await page.getByRole('checkbox', { name: /Comment by / }).check();
  await page.getByRole('checkbox', { name: /PARTIAL progress/ }).check();
  await page.getByRole('button', { name: 'Request exact preview' }).click();
  const preview = page.getByRole('region', { name: 'Exact sanitized public preview' });
  await expect(preview).toContainText('Exact private claim');
  await expect(preview).toContainText('The endpoint argument proves the exact claim.');
  await expect(preview).toContainText('The maximal-path endpoint needs degree one.');
  await expect(preview).toContainText('The dependency closure is ready for review.');
  await expect(preview).not.toContainText(privateMarker);
  const digestText = await preview.locator('p').first().textContent();
  const digest = digestText?.match(/digest (.+)$/)?.[1];
  expect(digest).toBeTruthy();
  await preview.getByRole('checkbox', { name: /I reviewed this exact server/ }).check();
  await preview.getByLabel('Publication reason').fill('Publish reviewed exact research.');

  const revoked = await page.request.patch(
    `${apiUrl}/api/v1/projects/${projectId}/members/${ownerId}`,
    { headers: human, data: { role: 'READ_ONLY' } },
  );
  expect(revoked.ok(), await revoked.text()).toBeTruthy();
  await preview.getByRole('button', { name: 'Confirm exact publication' }).click();
  await expect(page.getByRole('alert')).toContainText(/access changed|unavailable/i);
  await expect(page.getByRole('link', { name: /Open immutable public release/ })).toHaveCount(0);

  const restored = await page.request.patch(
    `${apiUrl}/api/v1/projects/${projectId}/members/${ownerId}`,
    {
      headers: { Authorization: 'Bearer contributor' },
      data: { role: 'OWNER' },
    },
  );
  expect(restored.ok(), await restored.text()).toBeTruthy();
  const confirmationRequest = page.waitForRequest(
    (request) =>
      request.method() === 'POST' &&
      new URL(request.url()).pathname === '/api/v1/publication/confirm',
  );
  await preview.getByRole('button', { name: 'Confirm exact publication' }).click();
  const originalConfirmation = await confirmationRequest;
  const releaseLink = page.getByRole('link', { name: /Open immutable public release/ });
  await expect(releaseLink).toBeVisible();
  const publicHref = await releaseLink.getAttribute('href');
  expect(publicHref).toMatch(/^\/commons\/publications\//);
  const manifestId = publicHref!.split('/').at(-1)!;

  const retryKey = await originalConfirmation.headerValue('Idempotency-Key');
  expect(retryKey).toBeTruthy();
  const retriedConfirmation = await page.request.post(`${apiUrl}/api/v1/publication/confirm`, {
    headers: { ...human, 'Idempotency-Key': retryKey! },
    data: originalConfirmation.postDataJSON(),
  });
  expect(retriedConfirmation.status(), await retriedConfirmation.text()).toBe(201);
  expect((await retriedConfirmation.json()).id).toBe(manifestId);

  await post(page.request, '/api/v1/records', {
    project_id: projectId,
    object_id: proof.id,
    base_revision_id: proof.revision_id,
    kind: 'PROOF_SKETCH',
    title: 'Later private proof revision',
    content_md: 'LATER PRIVATE EDIT MUST NOT APPEAR',
    assumptions_md: 'Finite nonempty tree.',
    statement_revision_ids: [claim.revision_id],
    reported_outcome: 'SUCCEEDED',
    reason: 'Continue privately after publication',
    proof_sketch: {
      conclusion_revision_id: claim.revision_id,
      premise_revision_ids: [],
      reported_progress: 'COMPLETE',
    },
  });

  const anonymous = await browser.newContext();
  try {
    const response = await anonymous.request.get(`${apiUrl}/api/v1/publications/${manifestId}`);
    expect(response.status()).toBe(200);
    const manifest = await response.json();
    expect(manifest.preview_digest).toBe(digest);
    expect(
      manifest.public_fields.records.map((item: { revision_id: string }) => item.revision_id),
    ).toEqual(expect.arrayContaining([proof.revision_id, claim.revision_id]));
    const serialized = JSON.stringify(manifest);
    expect(serialized).toContain('Choose a longest path');
    expect(serialized).not.toContain(privateMarker);
    expect(serialized).not.toContain('LATER PRIVATE EDIT MUST NOT APPEAR');
    expect(serialized).not.toContain(projectId);

    const publicPage = await anonymous.newPage();
    await publicPage.goto(`${webUrl}${publicHref}`);
    await expect(
      publicPage.getByRole('heading', { name: 'Immutable public research release' }),
    ).toBeVisible();
    await expect(
      publicPage.getByText('Choose a longest path and inspect an endpoint.'),
    ).toBeVisible();
    await expect(publicPage.getByText(privateMarker)).toHaveCount(0);
    await expect(publicPage.getByText('LATER PRIVATE EDIT MUST NOT APPEAR')).toHaveCount(0);
  } finally {
    await anonymous.close();
  }

  const noJs = await browser.newContext({ javaScriptEnabled: false });
  try {
    const readable = await noJs.newPage();
    const response = await readable.goto(`${apiUrl}/api/v1/publications/${manifestId}`);
    expect(response?.status()).toBe(200);
    const body = await readable.locator('body').textContent();
    expect(body).toContain('Choose a longest path');
    expect(body).not.toContain(privateMarker);
    expect(body).not.toContain('LATER PRIVATE EDIT MUST NOT APPEAR');
  } finally {
    await noJs.close();
  }

  expect(summary.current_revision.id).toBeTruthy();
  expect(comment.id).toBeTruthy();
  expect(progress.id).toBeTruthy();
});
