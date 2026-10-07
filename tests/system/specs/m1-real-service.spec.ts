import { expect, test, type APIRequestContext } from '@playwright/test';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const providerUrl = process.env.POLYCOLAB_INTEGRATION_PROVIDER_URL ?? 'http://127.0.0.1:18080';
const human = { Authorization: 'Bearer owner' };

async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${apiUrl}${path}`, {
    headers: { ...human, 'Idempotency-Key': crypto.randomUUID() },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test('M1 real worker writes publicly without private transcript or research disclosure', async ({
  request,
  page,
  browser,
}) => {
  test.setTimeout(90_000);
  const entry = await post(request, '/api/v1/catalogue', {
    kind: 'CLAIM',
    title: 'M1 sourced graph statement',
    content_md: 'Every graph in G has property P.',
    assumptions_md: 'G consists of finite connected graphs',
    source: { identifier: 'Integration source', version: '1', locator: 'Claim 1' },
    reported_status: 'OPEN',
    reason: 'Human admission',
  });
  const reference = await post(request, '/api/v1/workspace-references', {
    object_version_id: entry.object_version_id,
    workspace_name: 'M1 private investigation',
    reason: 'Investigate privately',
  });
  const privateMarker = `PRIVATE-CONTEXT-${crypto.randomUUID()}`;
  const privateReceipt = await post(request, '/api/v1/objects', {
    destination: { kind: 'workspace', workspace_id: reference.workspace_id },
    snapshot: {
      kind: 'NOTE',
      content: {
        title: privateMarker,
        content_md: privateMarker,
        assumptions_md: 'None stated',
        reported_outcome: null,
        explanation_md: null,
      },
      structural_relationships: [],
      change_summary: 'Private context only',
    },
  });
  const privateVersionId = privateReceipt.outputs.find(
    (output: { entity_type: string; entity_id: string }) => output.entity_type === 'OBJECT_VERSION',
  ).entity_id;
  const privateObjectId = privateReceipt.outputs.find(
    (output: { entity_type: string; entity_id: string }) =>
      output.entity_type === 'RESEARCH_OBJECT',
  ).entity_id;
  const session = await post(request, '/api/v1/agent-sessions', {
    workspace_id: reference.workspace_id,
    agent_kind: 'RESEARCHER',
    agent_version: 2,
  });
  async function profile(modelId: string) {
    return post(request, '/api/v1/gateway/profiles', {
      display_name: modelId,
      base_url: 'https://8.8.8.8/v1',
      model_id: modelId,
      api_key: 'local-integration-fixture-key',
    });
  }
  async function completed(runId: string) {
    await expect
      .poll(
        async () => {
          const response = await request.get(`${apiUrl}/api/v1/agent-runs/${runId}`, {
            headers: human,
          });
          expect(response.ok()).toBeTruthy();
          return (await response.json()).status;
        },
        { timeout: 30_000 },
      )
      .toBe('COMPLETED');
  }
  const privateProfile = await profile('integration-model');
  const privateTurn = await post(request, `/api/v1/agent-sessions/${session.id}/messages`, {
    client_request_id: crypto.randomUUID(),
    content_md: privateMarker,
    gateway_profile_id: privateProfile.id,
    context_object_version_ids: [privateVersionId],
  });
  await completed(privateTurn.run.id);
  const proposalsResponse = await request.get(
    `${apiUrl}/api/v1/workspaces/${reference.workspace_id}/proposals`,
    { headers: human },
  );
  expect(proposalsResponse.ok(), await proposalsResponse.text()).toBeTruthy();
  const proposals = await proposalsResponse.json();
  expect(proposals).toHaveLength(1);
  const detailResponse = await request.get(`${apiUrl}/api/v1/proposals/${proposals[0].id}`, {
    headers: human,
  });
  expect(detailResponse.ok(), await detailResponse.text()).toBeTruthy();
  const detail = await detailResponse.json();
  expect(detail.changes).toHaveLength(3);
  expect(detail.changes[0].payload).toMatchObject({
    kind: 'CREATE_OBJECT',
    snapshot: {
      kind: 'CLAIM',
      content: { title: 'Accepted finding', content_md: 'accepted', assumptions_md: 'None stated' },
      structural_relationships: [],
    },
  });
  const publicProfile = await profile('integration-direct-public');
  const publicTurn = await post(request, `/api/v1/agent-sessions/${session.id}/messages`, {
    client_request_id: crypto.randomUUID(),
    content_md: 'Explore the public graph statement.',
    gateway_profile_id: publicProfile.id,
    context_object_version_ids: [entry.object_version_id],
    requested_authority: {
      version: 1,
      destination: 'PUBLIC',
      public_target_object_version_ids: [entry.object_version_id],
      allowed_operations: ['CREATE_RECORD'],
      editable_object_ids: [],
      max_mutations: 1,
      max_content_bytes: 10000,
      public_task_md: 'Explore the public graph statement.',
    },
  });
  await completed(publicTurn.run.id);
  const result = await request.get(
    `${apiUrl}/api/v1/records?statement_id=${entry.object_version_id}`,
  );
  expect(result.status()).toBe(200);
  const records = (await result.json()).items;
  expect(records).toHaveLength(1);
  const record = records[0];
  expect(record).toMatchObject({
    authorship: { actor_kind: 'AGENT' },
    content: {
      reported_outcome: 'FAILED',
      assumptions_md: 'Finite connected graph',
      outcome: 'FAILED',
    },
  });
  expect(record.structural_relationships).toEqual(
    expect.arrayContaining(
      ['ATTACHMENT', 'TARGET'].map((relationship_type) =>
        expect.objectContaining({
          relationship_type,
          target_object_version_id: entry.object_version_id,
        }),
      ),
    ),
  );
  const calls = await (await request.get(`${providerUrl}/__test__/calls`)).json();
  const publicCalls = calls.filter(
    (call: { model: string }) => call.model === 'integration-direct-public',
  );
  expect(publicCalls).toHaveLength(3);
  for (const value of [JSON.stringify(publicCalls), JSON.stringify(records)]) {
    for (const secret of [
      privateMarker,
      privateObjectId,
      privateVersionId,
      reference.workspace_id,
      session.id,
    ])
      expect(value).not.toContain(secret);
  }
  for (const field of ['session_id', 'run_id', 'workspace_id', 'context_manifest_id'])
    expect(record).not.toHaveProperty(field);
  expect((await request.get(`${apiUrl}/api/v1/versions/${privateVersionId}`)).status()).toBe(404);
  await page.goto(`/commons/records/${record.id}`);
  await expect(
    page.getByRole('heading', { name: 'Direct public induction attempt' }),
  ).toBeVisible();
  await expect(page.getByText('The smaller graph need not satisfy the premise.')).toBeVisible();
  const anonymous = await browser.newContext();
  try {
    const readable = await anonymous.newPage();
    const response = await readable.goto(`${apiUrl}/commons/records/${record.id}`);
    expect(response?.status()).toBe(200);
    await expect(
      readable.getByRole('heading', { name: 'Direct public induction attempt' }),
    ).toBeVisible();
    expect(await readable.content()).not.toContain(privateMarker);
  } finally {
    await anonymous.close();
  }
});
