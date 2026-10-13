import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const verificationEnabled = process.env.POLYCOLAB_INTEGRATION_VERIFICATION === '1';
const human = { Authorization: 'Bearer owner' };

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${apiUrl}${path}`, {
    headers: { ...human, 'Idempotency-Key': crypto.randomUUID() },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
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

test('M3 real browser discovers, submits, inspects and cancels an exact queued job', async ({
  page,
}) => {
  test.skip(
    !verificationEnabled,
    'Requires the Platform-owned PostgreSQL/API/Garage harness with submission enabled and a curated Python environment seeded.',
  );
  test.setTimeout(90_000);
  await authenticate(page);

  const project = await post(page.request, '/api/v1/projects', {
    name: 'M3 verification project',
  });
  const projectId = project.id as string;
  const target = await post(page.request, '/api/v1/records', {
    project_id: projectId,
    kind: 'CLAIM',
    title: 'Exact bounded-computation target',
    content_md: 'The bounded computation checks this exact target.',
    assumptions_md: 'No machine result is treated as proof.',
    statement_revision_ids: [],
    reported_outcome: 'UNASSESSED',
    reason: 'Create the verification acceptance target',
  });
  const source = await post(page.request, '/api/v1/records', {
    project_id: projectId,
    kind: 'COMPUTATION',
    title: 'Exact Python acceptance source',
    content_md: 'print("bounded acceptance")',
    assumptions_md: 'CPython curated environment',
    statement_revision_ids: [target.revision_id],
    reported_outcome: 'IN_PROGRESS',
    reason: 'Create the exact saved source',
  });

  await page.goto(`/projects/${projectId}/verification`);
  await page.getByLabel('Filter environment language').selectOption('PYTHON');
  const environment = page.getByLabel('Exact curated environment');
  await expect.poll(() => environment.locator('option').count()).toBeGreaterThan(1);
  await environment.selectOption({ index: 1 });
  await page.getByLabel('Exact work-target version ID').fill(target.revision_id);
  await page.getByLabel('Exact saved source version ID').fill(source.revision_id);
  await page.getByLabel('Source path and entrypoint').fill('main.py');
  await page.getByLabel('Evidence scope').fill('Execute this exact saved source for this target.');
  await page.getByLabel('CPU count').fill('1');
  await page.getByLabel('CPU seconds').fill('5');
  await page.getByLabel('Wall seconds').fill('10');
  await page.getByLabel('Memory bytes').fill('16777216');
  await page.getByLabel('Process count').fill('1');
  await page.getByLabel('Disk bytes').fill('1048576');
  await page.getByLabel('Output bytes').fill('0');
  await page.getByLabel('Log bytes').fill('0');
  await page.getByLabel('Output files').fill('0');
  await page.getByRole('button', { name: 'Submit verification job' }).click();

  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/verification/[0-9a-f-]+$`));
  await expect(page.getByText('QUEUED', { exact: true })).toBeVisible();
  await expect(page.getByText(/#1 ADMITTED/)).toBeVisible();
  await expect(page.getByText(source.revision_id, { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel job' }).click();
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible();
  await expect(page.getByText(/#2 CANCELLED/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Rerun exact job' })).toBeDisabled();
  await expect(page.getByText(/Linux isolation gate/)).toBeVisible();
});
