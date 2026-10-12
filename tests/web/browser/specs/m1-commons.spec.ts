import { expect, test } from '../fixtures';
import type { components } from '../../../../src/web/src/lib/api-client/generated/schema';
import { claimVersion, versionAuthorship } from '../../unit/version-fixtures';

test('M1 admission to attempt, private reference, public direct turn, and suggestion', async ({
  page,
}) => {
  const entryId = '11111111-1111-4111-8111-111111111111';
  const revisionId = '22222222-2222-4222-8222-222222222222';
  const projectId = '33333333-3333-4333-8333-333333333333';
  const sessionId = '44444444-4444-4444-8444-444444444444';
  const now = '2026-09-07T00:00:00Z';
  type ObjectVersion = components['schemas']['PublicVersionedObjectRead']['current_object_version'];
  const saved: ObjectVersion[] = [];
  let admission: components['schemas']['CatalogueObjectAdmit'] | undefined;
  let queued: components['schemas']['AgentMessageCreate'] | undefined;
  let pinned = false;
  let correction: unknown;
  const project = {
    id: projectId,
    name: 'Private exploration',
    visibility: 'PRIVATE',
    current_user_role: 'OWNER',
    archived_at: null,
    created_at: now,
    updated_at: now,
  };
  const session = {
    id: sessionId,
    workspace_id: projectId,
    agent_version_id: 'researcher-v2',
    agent_version: 2,
    agent_kind: 'RESEARCHER',
    agent_display_name: 'Researcher',
    title: 'Explore',
    status: 'ACTIVE',
    created_at: now,
    updated_at: now,
  };
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/auth/config'
          ? { mode: 'local' }
          : { authenticated: true, username: 'ada', display_name: 'Ada' },
    }),
  );
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/v1/agent-capabilities')
      return route.fulfill({
        json: {
          sessions: true,
          execution_available: true,
          hosted_agents: false,
          verification: false,
        },
      });
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === '/api/v1/discovery')
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === '/api/v1/catalogue' && request.method() === 'POST') {
      admission = request.postDataJSON();
      expect(request.headers()['idempotency-key']).toBeTruthy();
      return route.fulfill({
        status: 201,
        json: { entry_id: entryId, object_version_id: revisionId },
      });
    }
    if (path === `/api/v1/catalogue/${entryId}`)
      return route.fulfill({
        json: {
          entry_id: entryId,
          admitted_at: now,
          source: admission!.source,
          reported_status: admission!.reported_status,
          object_version: claimVersion({
            object_id: entryId,
            id: revisionId,
            number: 1,
            previous_object_version_id: null,
            content: {
              title: admission!.title,
              content_md: admission!.content_md,
              assumptions_md: admission!.assumptions_md,
              reported_outcome: null,
              explanation_md: null,
            },
          }),
        },
      });
    if (path === '/api/v1/objects' && request.method() === 'POST') {
      const body = request.postDataJSON();
      if (body.catalogue_suggestion) correction = body.catalogue_suggestion;
      const record: ObjectVersion = {
        ...body.snapshot,
        object_id: crypto.randomUUID(),
        id: crypto.randomUUID(),
        schema_version: 1,
        previous_object_version_id: null,
        number: 1,
        authorship: versionAuthorship,
        created_at: now,
      };
      saved.push(record);
      return route.fulfill({
        status: 201,
        json: {
          contribution_id: crypto.randomUUID(),
          replayed: false,
          outputs: [
            { entity_type: 'RESEARCH_OBJECT', entity_id: record.object_id },
            { entity_type: 'OBJECT_VERSION', entity_id: record.id },
          ],
        },
      });
    }
    if (path === '/api/v1/records')
      return route.fulfill({ json: { items: saved, next_cursor: null } });
    if (path.endsWith('/summary')) return route.fulfill({ json: { items: [], status: 'PENDING' } });
    if (path === `/api/v1/community/${entryId}`)
      return route.fulfill({ json: { interest_count: 0 } });
    if (path === `/api/v1/community/${entryId}`)
      return route.fulfill({ json: { following: false, interested: false } });
    if (path === '/api/v1/workspace-references') {
      if (request.method() === 'POST') {
        expect(request.postDataJSON().object_version_id).toBe(revisionId);
        pinned = true;
      }
      const pin = {
        id: 'pin',
        workspace_id: projectId,
        object_id: entryId,
        object_version_id: revisionId,
        reference_version_id: 'pin-v1',
        previous_reference_version_id: null,
        number: 1,
        available: true,
        title: admission!.title,
        reason: 'Work privately',
        created_at: now,
      };
      return route.fulfill({
        json: request.method() === 'POST' ? pin : { items: pinned ? [pin] : [], next_cursor: null },
      });
    }
    if (path === `/api/v1/workspaces/${projectId}`) return route.fulfill({ json: project });
    if (path === '/api/v1/agent-sessions') return route.fulfill({ json: [session] });
    if (path === `/api/v1/agent-sessions/${sessionId}`) return route.fulfill({ json: session });
    if (path.endsWith('/gateway/profiles'))
      return route.fulfill({
        json: [{ id: 'profile', display_name: 'Research model', model_id: 'test' }],
      });
    if (path.endsWith('/platform-agents'))
      return route.fulfill({
        json: [
          { id: 'researcher-v2', agent_kind: 'RESEARCHER', version: 2, display_name: 'Researcher' },
        ],
      });
    if (path.endsWith('/messages')) {
      if (request.method() === 'POST') {
        queued = request.postDataJSON();
        const previous = saved[0]!;
        if (previous.kind !== 'ATTEMPT') throw new Error('Expected an attempt fixture');
        saved.push({
          ...previous,
          object_id: crypto.randomUUID(),
          id: crypto.randomUUID(),
          content: {
            ...previous.content,
            title: 'Agent follow-up attempt',
            content_md: 'A second approach also fails.',
          },
          authorship: {
            ...versionAuthorship,
            actor_kind: 'AGENT',
            agent_display_name: 'Researcher',
          },
        });
        return route.fulfill({
          status: 202,
          json: { run: { id: 'run', status: 'COMPLETED' }, message: { id: 'message' } },
        });
      }
      return route.fulfill({ json: [] });
    }
    if (path.endsWith('/events'))
      return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (path.endsWith('/objects') || path.endsWith('/proposals'))
      return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
  });
  await page.goto('/commons');
  await page.getByRole('button', { name: 'Contribute' }).click();
  await page.getByLabel('Title', { exact: true }).fill('Finite graph claim');
  await page.getByLabel('Formulation', { exact: true }).fill('Every graph in G has P.');
  await page.getByLabel('Assumptions', { exact: true }).fill('G is finite');
  await page.getByLabel('Source identifier').fill('Source');
  await page.getByLabel('Source version').fill('v1');
  await page.getByLabel('Source locator').fill('Claim 1');
  await page.getByLabel('Reported status').fill('OPEN');
  await page.getByRole('button', { name: 'Admit publicly' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(`/commons/${entryId}`);
  await page.getByRole('button', { name: 'Contribute research' }).click();
  await page.getByLabel('Title', { exact: true }).fill('Failed induction');
  await page.getByLabel('Research', { exact: true }).fill('The induction step fails.');
  await page.getByLabel('Attempt outcome').selectOption('FAILED');
  await page.getByLabel('Findings').fill('The hereditary step does not follow.');
  await page.getByLabel(/Evidence \(optional/).fill(`CONTRADICTS: ${revisionId}`);
  await page.getByLabel('Reported outcome').selectOption('FAILED');
  await page.getByLabel('Explanation (optional)').fill('The premise is not hereditary.');
  await page.getByRole('button', { name: 'Save public contribution' }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0]).toMatchObject({
    kind: 'ATTEMPT',
    content: {
      reported_outcome: 'FAILED',
      outcome: 'FAILED',
      findings_md: 'The hereditary step does not follow.',
    },
    structural_relationships: expect.arrayContaining([
      expect.objectContaining({
        relationship_type: 'ATTACHMENT',
        target_object_version_id: revisionId,
      }),
      expect.objectContaining({
        relationship_type: 'TARGET',
        target_object_version_id: revisionId,
      }),
      expect.objectContaining({
        relationship_type: 'EVIDENCE',
        target_object_version_id: revisionId,
        evidence_role: 'CONTRADICTS',
      }),
    ]),
  });
  await page.getByRole('button', { name: 'Research', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Failed induction' })).toBeVisible();
  await page.getByRole('button', { name: 'Work privately', exact: true }).click();
  await expect(page).toHaveURL(`/workspaces/${projectId}`);
  await page.goto(`/workspaces/${projectId}/references`);
  await expect(page.getByText('Pin version 1', { exact: false })).toBeVisible();
  await page.goto(`/workspaces/${projectId}/sessions/${sessionId}`);
  await page.getByLabel('AI provider').selectOption('profile');
  await page.getByLabel('Private message', { exact: true }).fill('PRIVATE DRAFT NEVER SENT');
  await page.getByText('Run settings', { exact: true }).click();
  await page.getByLabel('Contribution destination').selectOption('PUBLIC');
  await page
    .getByRole('checkbox', { name: 'Public contribution target: Finite graph claim' })
    .check();
  await page.getByLabel('Separate public task').fill('Explore the public statement');
  await page.getByRole('button', { name: 'Authorize public contribution run' }).click();
  await expect.poll(() => queued?.requested_authority?.destination).toBe('PUBLIC');
  expect(JSON.stringify(queued)).not.toContain('PRIVATE DRAFT NEVER SENT');
  expect(queued!.context_object_version_ids).toEqual([revisionId]);
  await page.goto(`/commons/${entryId}`);
  await page.getByRole('button', { name: 'Research', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Agent follow-up attempt' })).toBeVisible();
  await expect(page.getByText('A second approach also fails.')).toBeVisible();
  await page.getByRole('button', { name: 'Statement', exact: true }).click();
  await page.getByRole('button', { name: 'Prepare a formulation change' }).click();
  await page.getByLabel('Formulation', { exact: true }).fill('A corrected formulation');
  await page.getByLabel('Reason', { exact: true }).fill('Clarify the premise');
  await page.getByRole('button', { name: 'Submit public suggestion' }).click();
  await expect(page.getByRole('link', { name: 'Read the exact saved version' })).toBeVisible();
  expect(saved[2]).toMatchObject({
    kind: 'NOTE',
    content: { content_md: 'Clarify the premise' },
  });
  expect(correction).toMatchObject({
    expected_current_object_version_id: revisionId,
    content_md: 'A corrected formulation',
  });
});
