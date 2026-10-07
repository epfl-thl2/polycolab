import { expect, test, type Page } from '../fixtures';
import { claimVersion } from '../../unit/version-fixtures';

const projectId = '11111111-1111-1111-1111-111111111111';
const proposalId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const changeOne = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
const changeTwo = 'cccccccc-cccc-cccc-cccc-cccccccccccc';

interface ProjectResponse {
  id: string;
  name: string;
  description: string | null;
  visibility: string;
  archived_at: string | null;
  current_user_role: string;
}

const project: ProjectResponse = {
  id: projectId,
  name: 'Private project',
  description: null,
  visibility: 'PRIVATE',
  archived_at: null,
  current_user_role: 'CONTRIBUTOR',
};

const manifest = {
  id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
  run_id: 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
  workspace_id: projectId,
  object_version_ids: ['ffffffff-ffff-ffff-ffff-ffffffffffff'],
  artifact_ids: [],
  digest: 'a'.repeat(64),
  created_at: '2026-01-01T00:00:00Z',
  object_versions: [
    claimVersion({
      id: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
      object_id: '99999999-9999-9999-9999-999999999999',
      number: 2,
      content: {
        ...claimVersion().content,
        title: 'Exact source claim',
        content_md: 'The exact context supplied to the agent.',
      },
      previous_object_version_id: '88888888-8888-8888-8888-888888888888',
      created_at: '2026-01-01T00:00:00Z',
    }),
  ],
};

async function authenticate(page: Page) {
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'contributor', display_name: 'Contributor' },
    }),
  );
}

function proposalDetail() {
  return {
    id: proposalId,
    workspace_id: projectId,
    agent_version_id: 'agent-version-1',
    context_manifest_id: manifest.id,
    summary: 'Agent found two changes',
    created_at: '2026-01-01T00:00:00Z',
    changes: [
      {
        id: changeOne,
        ordinal: 1,
        change_type: 'CREATE_OBJECT',
        payload: { kind: 'CREATE_OBJECT', title: 'New claim', content_md: 'x' },
        status: 'PENDING',
        decided_at: null,
        decided_by_user_id: null,
        applied_entity_id: null,
        rejection_reason: null,
      },
      {
        id: changeTwo,
        ordinal: 2,
        change_type: 'CREATE_COMMENT',
        payload: {
          kind: 'CREATE_COMMENT',
          object_id: '99999999-9999-9999-9999-999999999999',
          revision_id: manifest.object_version_ids[0],
          body_md: 'Comment',
        },
        status: 'PENDING',
        decided_at: null,
        decided_by_user_id: null,
        applied_entity_id: null,
        rejection_reason: null,
      },
    ],
  };
}

test('contributor reviews an inbox proposal with partial per-change decisions', async ({
  page,
}) => {
  await authenticate(page);
  let detail = proposalDetail();
  let batchRequests = 0;
  let decisionKey = '';
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === `/api/v1/workspaces/${projectId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(project) });
    if (path === `/api/v1/workspaces/${projectId}/proposals`)
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: proposalId,
            workspace_id: projectId,
            agent_version_id: 'agent-version-1',
            context_manifest_id: manifest.id,
            summary: 'Agent found two changes',
            created_at: '2026-01-01T00:00:00Z',
          },
        ]),
      });
    if (path === `/api/v1/proposals/${proposalId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(detail) });
    if (path === `/api/v1/proposals/${proposalId}/context`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(manifest) });
    if (path === `/api/v1/proposals/${proposalId}/decisions` && request.method() === 'POST') {
      batchRequests += 1;
      decisionKey = request.headers()['idempotency-key'] ?? '';
      const input = request.postDataJSON() as {
        decisions: { change_id: string; action: 'ACCEPT' | 'REJECT' }[];
      };
      const changed = input.decisions.map((decision) => {
        const current = detail.changes.find((change) => change.id === decision.change_id)!;
        return { ...current, status: decision.action === 'ACCEPT' ? 'ACCEPTED' : 'REJECTED' };
      });
      detail = {
        ...detail,
        changes: detail.changes.map(
          (change) => changed.find((item) => item.id === change.id) ?? change,
        ),
      };
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(changed) });
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.goto(`/projects/${projectId}/proposals`);
  await expect(page.getByRole('heading', { name: 'Proposal review', level: 1 })).toBeVisible();
  await page.getByRole('link', { name: /Agent found two changes/ }).click();
  await expect(page.getByRole('heading', { name: 'Agent found two changes' })).toBeVisible();
  await expect(page.getByText('The exact context supplied to the agent.')).not.toBeVisible();
  await page.getByText('Show source content').click();
  await expect(page.getByText('The exact context supplied to the agent.')).toBeVisible();

  await page.getByLabel('Select change 1').check();
  await page.getByLabel('Decision for change 2').selectOption('REJECT');
  await page.getByLabel('Reason for selected rejections').fill('Needs a human rewrite.');
  await page.getByLabel('Select change 2').check();
  await page.getByRole('button', { name: 'Apply 2 selected decisions' }).click();
  await expect(page.getByText('Selected decisions applied together.')).toBeVisible();
  await expect(page.getByText('ACCEPTED')).toBeVisible();
  await expect(page.getByText('REJECTED')).toBeVisible();
  expect(batchRequests).toBe(1);
  expect(decisionKey).toMatch(/^[0-9a-f-]{36}$/);
});

test('stale atomic batch preserves every selected draft and applies no partial status', async ({
  page,
}) => {
  await authenticate(page);
  const detail = proposalDetail();
  let batchRequests = 0;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === `/api/v1/workspaces/${projectId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(project) });
    if (path === `/api/v1/proposals/${proposalId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(detail) });
    if (path === `/api/v1/proposals/${proposalId}/context`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(manifest) });
    if (path === `/api/v1/proposals/${proposalId}/decisions` && request.method() === 'POST') {
      batchRequests += 1;
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'stale_proposal' } }),
      });
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.goto(`/projects/${projectId}/proposals/${proposalId}`);
  const firstChange = page.locator('section.card').filter({
    has: page.getByRole('checkbox', { name: 'Select change 1' }),
  });
  const draft = firstChange.getByLabel('Title');
  await draft.fill('Preserved edit');
  await page.getByLabel('Select change 1').check();
  await page.getByLabel('Decision for change 2').selectOption('REJECT');
  await page.getByLabel('Reason for selected rejections').fill('Preserved reason');
  await page.getByLabel('Select change 2').check();
  await page.getByRole('button', { name: 'Apply 2 selected decisions' }).click();

  await expect(page.getByRole('alert')).toContainText('draft is retained');
  await expect(page.getByText('PENDING')).toHaveCount(2);
  await expect(page.getByLabel('Select change 1')).toBeChecked();
  await expect(page.getByLabel('Select change 2')).toBeChecked();
  await expect(draft).toHaveValue('Preserved edit');
  await expect(page.getByLabel('Reason for selected rejections')).toHaveValue('Preserved reason');
  expect(batchRequests).toBe(1);
});

test('cross-member reviewer keeps decision controls while private source context stays hidden', async ({
  page,
}) => {
  await authenticate(page);
  const detail = proposalDetail();
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === `/api/v1/workspaces/${projectId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(project) });
    if (path === `/api/v1/proposals/${proposalId}`)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(detail) });
    if (path === `/api/v1/proposals/${proposalId}/context`)
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'not_found' } }),
      });
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.goto(`/projects/${projectId}/proposals/${proposalId}`);
  await expect(
    page.getByRole('heading', { name: 'Sources private to requesting contributor' }),
  ).toBeVisible();
  await expect(page.getByLabel('Select change 1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply 0 selected decisions' })).toBeVisible();
  await expect(page.getByText('The exact context supplied to the agent.')).toHaveCount(0);
});

test('read-only and archived project members never fetch or render proposal data', async ({
  page,
}) => {
  await authenticate(page);
  let proposalRequests = 0;
  let projectResponse = { ...project, current_user_role: 'READ_ONLY' };
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path.endsWith('/proposals') || path.includes('/proposals/')) proposalRequests += 1;
    const readOnly = path.endsWith(`/workspaces/${projectId}`) ? projectResponse : [];
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(readOnly) });
  });
  await page.goto(`/projects/${projectId}/proposals`);
  await expect(
    page.getByText('Review requires an active contributor or owner role.'),
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Proposal review unavailable' })).toBeVisible();
  projectResponse = { ...project, archived_at: '2026-01-01T00:00:00Z' };
  await page.reload();
  await expect(page.getByText('This workspace is archived and cannot be changed.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Proposal review unavailable' })).toBeVisible();
  expect(proposalRequests).toBe(0);
});
