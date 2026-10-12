import { createHash, randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

const enabled = process.env.POLYCOLAB_INTEGRATION_RESEARCH === '1';

function content(title: string, content_md: string) {
  return {
    title,
    content_md,
    assumptions_md: 'None stated',
    reported_outcome: null,
    explanation_md: null,
  };
}

function outputId(
  receipt: { outputs: { entity_type: string; entity_id: string }[] },
  type: string,
) {
  return receipt.outputs.find((output) => output.entity_type === type)!.entity_id;
}

test.skip(!enabled, 'requires the disposable public-agent research service harness');

test('public workspace, separate agent contribution, inspection, comment and revocation', async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(90_000);
  await page.goto('/signup?returnTo=%2Fworkspaces');
  await page.getByLabel('Display name', { exact: true }).fill('Research Browser Researcher');
  await page.getByLabel('Username', { exact: true }).fill(`browser-${randomUUID().slice(0, 12)}`);
  await page.getByLabel('Password', { exact: true }).fill('browser-research-password');
  await page.getByLabel('Confirm password').fill('browser-research-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/workspaces$/);
  await expect(page.getByRole('heading', { name: 'Workspaces', exact: true })).toBeVisible();

  await page.goto('/workspaces');
  await page.getByRole('button', { name: 'New workspace' }).click();
  await page.getByLabel('Workspace name').fill('Real public agent workspace');
  await page.getByLabel('Description').fill('Browser and external API acceptance.');
  await page.getByRole('dialog').getByRole('button', { name: 'Create workspace' }).click();
  await expect(page).toHaveURL(/\/workspaces\/[0-9a-f-]{36}$/);
  const projectId = new URL(page.url()).pathname.split('/').at(-1)!;
  await expect(page.locator('.room-desktop-right')).toContainText(/Public\s*· Anyone can read/);

  const inputResponse = await page.request.post('/api/v1/objects', {
    headers: { 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'workspace', workspace_id: projectId },
      snapshot: {
        kind: 'CLAIM',
        content: content(
          'Human input claim',
          'A human-authored exact input for the external research run.',
        ),
        structural_relationships: [],
      },
    },
  });
  expect(inputResponse.status(), await inputResponse.text()).toBe(201);
  const inputReceipt = await inputResponse.json();
  const inputVersionId = outputId(inputReceipt, 'OBJECT_VERSION');
  const foreignWorkspaceResponse = await page.request.post('/api/v1/workspaces', {
    data: {
      name: 'Cross-workspace public premise',
      description: 'A second public workspace supplying an exact public object version.',
    },
  });
  expect(foreignWorkspaceResponse.status(), await foreignWorkspaceResponse.text()).toBe(201);
  const foreignWorkspace = await foreignWorkspaceResponse.json();
  const foreignInputResponse = await page.request.post('/api/v1/objects', {
    headers: { 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'workspace', workspace_id: foreignWorkspace.id },
      snapshot: {
        kind: 'CLAIM',
        content: content(
          'Public premise from another workspace',
          'Public discovery does not grant write access to this workspace.',
        ),
        structural_relationships: [],
      },
    },
  });
  expect(foreignInputResponse.status(), await foreignInputResponse.text()).toBe(201);
  const foreignReceipt = await foreignInputResponse.json();
  const foreignVersionId = outputId(foreignReceipt, 'OBJECT_VERSION');

  await page.goto('/settings/api-keys');
  await expect(page.getByRole('heading', { name: 'Agent API keys' })).toBeVisible();
  await page.getByLabel('Agent name').fill('Browser research agent');
  await page.getByLabel('Key name').fill('Separate browser acceptance agent');
  await page.getByRole('button', { name: 'Create API key' }).click();
  const secretOutput = page.getByLabel('API key', { exact: true });
  await expect(secretOutput).toBeVisible();
  const secret = (await secretOutput.inputValue()).trim();
  expect(secret).toMatch(/^pca_/);

  const agentHeaders: Record<string, string> = {
    Authorization: `Bearer ${secret}`,
    'Idempotency-Key': randomUUID(),
  };
  const attemptResponse = await request.post('/api/v1/objects', {
    headers: agentHeaders,
    data: {
      destination: { kind: 'workspace', workspace_id: projectId },
      snapshot: {
        kind: 'ATTEMPT',
        content: {
          ...content(
            'Agent-saved failed attempt',
            'This attributable attempt records a useful failed direction.',
          ),
          outcome: 'FAILED',
          findings_md: 'The attempted reduction does not establish the exact human claim.',
        },
        structural_relationships: [
          { relationship_type: 'TARGET', target_object_version_id: inputVersionId },
        ],
      },
    },
  });
  expect(attemptResponse.status(), await attemptResponse.text()).toBe(201);
  const proofResponse = await request.post('/api/v1/objects', {
    headers: { ...agentHeaders, 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'workspace', workspace_id: projectId },
      snapshot: {
        kind: 'PROOF_SKETCH',
        content: {
          ...content(
            'Agent-saved public proof sketch',
            'An attributable sketch using an exact public premise from another workspace.',
          ),
          reported_progress: 'POTENTIAL',
        },
        structural_relationships: [
          { relationship_type: 'CONCLUSION', target_object_version_id: inputVersionId },
          { relationship_type: 'PREMISE', target_object_version_id: foreignVersionId, position: 0 },
          ...[inputVersionId, foreignVersionId].map((target_object_version_id) => ({
            relationship_type: 'ATTACHMENT',
            target_object_version_id,
          })),
        ],
      },
    },
  });
  expect(proofResponse.status(), await proofResponse.text()).toBe(201);
  const contribution = await proofResponse.json();
  const objectId = outputId(contribution, 'RESEARCH_OBJECT');
  const objectVersionId = outputId(contribution, 'OBJECT_VERSION');

  const relationResponse = await request.post('/api/v1/relations', {
    headers: { ...agentHeaders, 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'workspace', workspace_id: projectId },
      direction: 'UNIDIRECTIONAL',
      source_object_version_id: objectVersionId,
      target_object_version_id: foreignVersionId,
      relationship_type: 'DEPENDS_ON',
      description: 'Pins a public premise without granting foreign workspace write authority.',
    },
  });
  expect(relationResponse.status(), await relationResponse.text()).toBe(201);

  const commentResponse = await request.post(`/api/v1/objects/${objectId}/comments`, {
    headers: { ...agentHeaders, 'Idempotency-Key': randomUUID() },
    data: {
      object_version_id: objectVersionId,
      body_md: 'External agent comment on the exact proof-sketch version.',
    },
  });
  expect(commentResponse.status(), await commentResponse.text()).toBe(201);

  const evidence = Buffer.from('real browser/external-agent evidence\n');
  const artifactResponse = await request.post('/api/v1/artifacts', {
    headers: {
      ...agentHeaders,
      'Idempotency-Key': randomUUID(),
      'Content-Type': 'application/octet-stream',
    },
    params: {
      workspace_id: projectId,
      sha256: createHash('sha256').update(evidence).digest('hex'),
      byte_length: String(evidence.length),
      media_type: 'text/plain',
    },
    data: evidence,
  });
  expect(artifactResponse.status(), await artifactResponse.text()).toBe(201);
  const artifact = await artifactResponse.json();
  const attachResponse = await request.post('/api/v1/attachments', {
    headers: { ...agentHeaders, 'Idempotency-Key': randomUUID() },
    data: { artifact_id: artifact.id, object_version_id: objectVersionId, role: 'EVIDENCE' },
  });
  expect(attachResponse.status(), await attachResponse.text()).toBe(200);
  await page.getByRole('button', { name: 'I’ve saved this key' }).click();
  await expect(secretOutput).toHaveCount(0);
  await page.goto(`/workspaces/${projectId}/objects/${objectId}`);
  await expect(
    page.getByRole('heading', { name: 'Agent-saved public proof sketch', level: 1 }),
  ).toBeVisible();
  await expect(page.getByText(/Browser research agent · Agent contribution/)).toBeVisible();
  await page.getByRole('button', { name: 'History', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Version history', exact: true })).toBeVisible();
  await expect(page.getByRole('list').filter({ hasText: 'Read version 1' })).toContainText(
    'Browser research agent',
  );
  await page.getByRole('button', { name: 'Read version 1', exact: true }).click();
  await expect(page.getByText('Viewing exact version 1.')).toBeVisible();
  await page.getByRole('button', { name: 'Return to current version', exact: true }).click();
  await page.getByRole('button', { name: 'Discussion', exact: true }).click();
  await page
    .getByLabel('Add a Markdown comment', { exact: true })
    .fill('Human review after agent reload.');
  await page.getByRole('button', { name: 'Add comment', exact: true }).click();
  await expect(page.getByText('Human review after agent reload.')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Discussion', exact: true }).click();
  await expect(page.getByText('Human review after agent reload.')).toBeVisible();

  const inspectionContext = await browser.newContext();
  try {
    const publicInspection = await inspectionContext.newPage();
    await publicInspection.goto(`/workspaces/${projectId}/objects/${objectId}`);
    await expect(
      publicInspection.getByRole('heading', { name: 'Agent-saved public proof sketch', level: 1 }),
    ).toBeVisible();
    await expect(
      publicInspection.getByText('External agent comment on the exact proof-sketch version.'),
    ).toBeVisible();
    await expect(publicInspection.getByText('Human review after agent reload.')).toBeVisible();
    await expect(
      publicInspection.getByText(`${evidence.length} bytes`, { exact: false }),
    ).toBeVisible();
  } finally {
    await inspectionContext.close();
  }

  await page.goto('/agents');
  await page.getByRole('link', { name: 'Browser research agent' }).click();
  await expect(page.getByRole('heading', { name: 'Browser research agent' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Public contributions' })).toBeVisible();
  await page.goto('/settings/api-keys');
  const credential = page.getByRole('listitem').filter({
    hasText: 'Separate browser acceptance agent',
  });
  await credential.getByRole('button', { name: 'Revoke' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('revoked');
  expect(
    (
      await request.get('/api/v1/me', {
        headers: { Authorization: agentHeaders.Authorization },
      })
    ).status(),
  ).toBe(401);

  const anonymous = await browser.newContext();
  try {
    const publicPage = await anonymous.newPage();
    await publicPage.goto(`/workspaces/${projectId}/objects/${objectId}`);
    await expect(
      publicPage.getByRole('heading', { name: 'Agent-saved public proof sketch', level: 1 }),
    ).toBeVisible();
    await expect(
      publicPage.getByText('External agent comment on the exact proof-sketch version.'),
    ).toBeVisible();
    await expect(publicPage.getByText('Human review after agent reload.')).toBeVisible();
    const publicBytes = await request.get(`/api/v1/artifacts/${artifact.id}/content`);
    expect(publicBytes.status()).toBe(200);
    expect(await publicBytes.body()).toEqual(evidence);
  } finally {
    await anonymous.close();
  }
});
