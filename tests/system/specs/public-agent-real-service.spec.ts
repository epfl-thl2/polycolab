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

test('public project, separate agent contribution, inspection, comment and revocation', async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(90_000);
  await page.goto('/signup?returnTo=%2Fprojects');
  await page.getByLabel('Display name', { exact: true }).fill('Research Browser Researcher');
  await page.getByLabel('Username', { exact: true }).fill(`browser-${randomUUID().slice(0, 12)}`);
  await page.getByLabel('Password', { exact: true }).fill('browser-research-password');
  await page.getByLabel('Confirm password').fill('browser-research-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();

  await page.goto('/projects');
  await page.getByRole('button', { name: 'New project' }).click();
  await page.getByLabel('Project name').fill('Real public agent project');
  await page.getByLabel('Description').fill('Browser and external API acceptance.');
  await page.getByRole('dialog').getByRole('button', { name: 'Create project' }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}(?:\/sessions\/new)?$/);
  const projectId = new URL(page.url()).pathname.split('/')[2]!;
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Overview', exact: true })
    .click();
  await expect(page.getByRole('main')).toContainText('Public');

  const inputResponse = await page.request.post('/api/v1/objects', {
    headers: { 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'project', project_id: projectId },
      snapshot: {
        kind: 'STATEMENT',
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
  const foreignProjectResponse = await page.request.post('/api/v1/projects', {
    data: {
      name: 'Cross-project public premise',
      description: 'A second public project supplying an exact public object version.',
    },
  });
  expect(foreignProjectResponse.status(), await foreignProjectResponse.text()).toBe(201);
  const foreignProject = await foreignProjectResponse.json();
  const foreignInputResponse = await page.request.post('/api/v1/objects', {
    headers: { 'Idempotency-Key': randomUUID() },
    data: {
      destination: { kind: 'project', project_id: foreignProject.id },
      snapshot: {
        kind: 'STATEMENT',
        content: content(
          'Public premise from another project',
          'Public discovery does not grant write access to this project.',
        ),
        structural_relationships: [],
      },
    },
  });
  expect(foreignInputResponse.status(), await foreignInputResponse.text()).toBe(201);
  const foreignReceipt = await foreignInputResponse.json();
  const foreignVersionId = outputId(foreignReceipt, 'OBJECT_VERSION');

  await page.goto('/settings/api-keys');
  await expect(page.getByRole('table', { name: 'Your API keys' })).toBeVisible();
  await page.getByRole('button', { name: 'New API key', exact: true }).click();
  await page.getByLabel('Polycolab agent name').fill('Browser research agent');
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
      destination: { kind: 'project', project_id: projectId },
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
      destination: { kind: 'project', project_id: projectId },
      snapshot: {
        kind: 'PROOF',
        content: {
          ...content(
            'Agent-saved public proof sketch',
            'An attributable sketch using an exact public premise from another project.',
          ),
          reported_progress: 'PARTIAL',
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
      destination: { kind: 'project', project_id: projectId },
      direction: 'UNIDIRECTIONAL',
      source_object_version_id: objectVersionId,
      target_object_version_id: foreignVersionId,
      relationship_type: 'DEPENDS_ON',
      description: 'Pins a public premise without granting foreign project write authority.',
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
      project_id: projectId,
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
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(secretOutput).toHaveCount(0);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
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

  const inspectionContext = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const publicInspection = await inspectionContext.newPage();
    await publicInspection.goto(`/projects/${projectId}/objects/${objectId}`);
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

  await page.goto('/agents/connections');
  await page.getByRole('link', { name: 'Browser research agent' }).click();
  await expect(page.getByRole('heading', { name: 'Browser research agent' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Public contributions' })).toBeVisible();
  await page.goto('/settings/api-keys');
  const credential = page.getByRole('row').filter({
    hasText: 'Separate browser acceptance agent',
  });
  await credential
    .getByRole('button', { name: 'Actions for Separate browser acceptance agent' })
    .click();
  await page.getByRole('menuitem', { name: 'Revoke key', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('revoked');
  expect(
    (
      await request.get('/api/v1/me', {
        headers: { Authorization: agentHeaders.Authorization },
      })
    ).status(),
  ).toBe(401);

  const anonymous = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const publicPage = await anonymous.newPage();
    await publicPage.goto(`/projects/${projectId}/objects/${objectId}`);
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

test('agent library publishes, preserves private drafts, and makes attributed copies', async ({
  page,
  browser,
}) => {
  test.setTimeout(90_000);
  async function signUp(target: typeof page, label: string) {
    const errors: string[] = [];
    target.on('pageerror', (error) => errors.push(error.message));
    await target.goto('/signup?returnTo=%2Fagents%2Fyours');
    const configuration = await target.request.get('/auth/config');
    expect(configuration.status()).toBe(200);
    expect((await configuration.json()).registration_mode).toBe('open');
    try {
      await expect(target.getByLabel('Display name', { exact: true })).toBeVisible({
        timeout: 15_000,
      });
    } catch (error) {
      // This runs before credentials or private content are entered.
      console.log(
        'Error: library signup page did not initialize',
        JSON.stringify({ errors, headings: await target.locator('h1').allTextContents() }),
      );
      throw error;
    }
    await target.getByLabel('Display name', { exact: true }).fill(label);
    await target
      .getByLabel('Username', { exact: true })
      .fill(`library-${randomUUID().slice(0, 12)}`);
    await target.getByLabel('Password', { exact: true }).fill('library-browser-password');
    await target.getByLabel('Confirm password').fill('library-browser-password');
    await target.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(target).toHaveURL(/\/agents\/yours$/);
  }
  await signUp(page, 'Library Author');
  await page.getByRole('link', { name: 'Contribute', exact: true }).click();
  const title = `Proof inspection ${randomUUID().slice(0, 8)}`;
  await page.getByLabel('Title', { exact: true }).fill(title);
  await page
    .getByLabel('Description', { exact: true })
    .fill('Check each inference and assumption.');
  await page
    .getByLabel('Prompt text', { exact: true })
    .fill('Inspect every inference in the selected proof.');
  await page.getByLabel('License', { exact: true }).fill('CC-BY-4.0');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page).toHaveURL(/\/agents\/yours\/[0-9a-f-]+\/edit$/);
  const entryId = new URL(page.url()).pathname.split('/')[3]!;
  const anonymous = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const second = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const publicPage = await anonymous.newPage();
    const privateRead = await publicPage.request.get(`/api/v1/agent-library/${entryId}/draft`);
    expect(privateRead.status()).toBe(401);
    expect((await publicPage.request.get(`/api/v1/agent-library/${entryId}`)).status()).toBe(404);
    await page.getByRole('button', { name: 'Preview publication', exact: true }).click();
    await page.getByRole('button', { name: 'Publish', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Published version 1');
    await page.getByRole('link', { name: 'View published version', exact: true }).first().click();
    await expect(page).toHaveURL(/\/agents\/library\/[0-9a-f-]+\/versions\/[0-9a-f-]+$/);
    const exactUrl = page.url();
    const versionId = new URL(exactUrl).pathname.split('/')[5]!;
    await publicPage.goto('/agents');
    await publicPage.getByLabel('Search', { exact: true }).fill(title);
    await publicPage.getByRole('button', { name: 'Search', exact: true }).click();
    await publicPage.getByRole('link', { name: title, exact: true }).click();
    await expect(
      publicPage.getByText('Inspect every inference in the selected proof.', { exact: true }),
    ).toBeVisible();
    await publicPage.reload();
    await expect(publicPage.getByRole('heading', { name: title, exact: true })).toBeVisible();
    const copyPage = await second.newPage();
    await signUp(copyPage, 'Library Adapter');
    await copyPage.goto(exactUrl);
    await copyPage.getByRole('button', { name: 'Make a copy', exact: true }).click();
    await expect(copyPage).toHaveURL(/\/agents\/yours\/[0-9a-f-]+\/edit$/);
    await expect(
      copyPage.getByRole('link', { name: 'View original version', exact: true }),
    ).toHaveAttribute('href', `/agents/library/${entryId}/versions/${versionId}`);
    await copyPage.reload();
    await expect(copyPage.getByLabel('Prompt text', { exact: true })).toHaveValue(
      'Inspect every inference in the selected proof.',
    );
    const copyId = new URL(copyPage.url()).pathname.split('/')[3]!;
    expect((await publicPage.request.get(`/api/v1/agent-library/${copyId}`)).status()).toBe(404);
    await page.goto(`/agents/yours/${entryId}/edit`);
    await page
      .getByLabel('Prompt text', { exact: true })
      .fill('PRIVATE DRAFT — keep outside public views');
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Private draft saved');
    await publicPage.goto(exactUrl);
    await expect(
      publicPage.getByText('PRIVATE DRAFT — keep outside public views', { exact: true }),
    ).toHaveCount(0);
    await page.getByLabel('Prompt text', { exact: true }).fill('Second published instructions.');
    await page.getByRole('button', { name: 'Preview publication', exact: true }).click();
    await page.getByRole('button', { name: 'Publish', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Published version 2');
    await publicPage.reload();
    await expect(
      publicPage.getByText('Inspect every inference in the selected proof.', { exact: true }),
    ).toBeVisible();
    await publicPage.goto(`/agents/library/${entryId}`);
    await expect(
      publicPage.getByText('Second published instructions.', { exact: true }),
    ).toBeVisible();
  } finally {
    await anonymous.close();
    await second.close();
  }
});
