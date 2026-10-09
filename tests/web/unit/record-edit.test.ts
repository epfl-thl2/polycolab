import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import RecordEdit from '../../../src/web/src/ui/RecordEdit.svelte';
import { contextKey } from '../../../src/web/src/svelte-lib/context';
import type { RecordRead } from '../../../src/web/src/lib/records-api';

afterEach(cleanup);
const record: RecordRead = {
  schema_version: 1,
  structural_relationships: ['ATTACHMENT', 'TARGET'].map((role) => ({
    id: `relationship-${role}`,
    direction: 'UNIDIRECTIONAL',
    binding: 'STRUCTURAL',
    relationship_type: role as 'ATTACHMENT' | 'TARGET',
    source_object_version_id: 'old',
    target_object_version_id: 'exact-statement',
    position: null,
    evidence_role: null,
    ownership_scope_id: 'workspace-scope',
    description: null,
    created_at: '2026-09-07T00:00:00Z',
    authorship: {
      actor_kind: 'HUMAN',
      author_display_name: 'Ada',
      agent_display_name: null,
      author_user_id: null,
      agent_id: null,
      contribution_id: null,
      sponsor_user_id: null,
    },
  })),
  object_id: 'object',
  id: 'old',
  previous_object_version_id: null,
  number: 1,
  kind: 'ATTEMPT',
  legacy_unstructured: false,
  change_summary: null,
  content: {
    title: 'Failed induction',
    content_md: 'Inductive step fails',
    assumptions_md: 'Finite graph',
    reported_outcome: 'FAILED',
    explanation_md: 'The smaller graph need not satisfy the premise',
    outcome: 'FAILED',
    findings_md: 'The premise is not inductive',
  },
  authorship: {
    actor_kind: 'HUMAN',
    author_display_name: 'Ada',
    agent_display_name: null,
    author_user_id: null,
    agent_id: null,
    contribution_id: null,
    sponsor_user_id: null,
  },
  created_at: '2026-09-07T00:00:00Z',
};

it('keeps private edit metadata and exact pins through conflict and explicit rebasing', async () => {
  const write = vi
    .fn()
    .mockRejectedValueOnce({ status: 409 })
    .mockResolvedValue({ current_object_version_id: 'saved' });
  const workspaceList = vi.fn().mockResolvedValue({
    items: [{ ...record, id: 'new', number: 2 }],
    next_cursor: null,
  });
  const list = vi.fn();
  const invalidateQueries = vi.fn();
  render(RecordEdit, {
    props: { record, projectId: 'workspace' },
    context: new Map([
      [
        contextKey,
        {
          api: { createVersion: write },
          records: { workspaceList, list },
          query: { invalidateQueries },
        },
      ],
    ]),
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Edit from this exact version' }));
  await fireEvent.input(screen.getByLabelText('Research'), {
    target: { value: 'Retained private draft' },
  });
  await fireEvent.input(screen.getByLabelText('Change summary'), {
    target: { value: 'Explain failure' },
  });
  await fireEvent.click(screen.getByRole('button', { name: 'Save record version' }));
  await screen.findByRole('alert');
  await fireEvent.click(screen.getByRole('button', { name: 'Reload visible version history' }));
  await fireEvent.click(await screen.findByRole('button', { name: 'Compare this version' }));
  expect(write).toHaveBeenCalledTimes(1);
  await fireEvent.click(
    screen.getByRole('button', { name: 'Use this exact base, retaining my draft' }),
  );
  await fireEvent.click(screen.getByRole('button', { name: 'Save record version' }));
  await waitFor(() => expect(write).toHaveBeenCalledTimes(2));
  expect(write.mock.calls[1]![0]).toBe('object');
  expect(write.mock.calls[1]![1]).toMatchObject({
    expected_current_object_version_id: 'new',
    snapshot: {
      content: {
        content_md: 'Retained private draft',
        assumptions_md: record.content.assumptions_md,
        reported_outcome: 'FAILED',
        explanation_md: record.content.explanation_md,
      },
      structural_relationships: [
        { relationship_type: 'ATTACHMENT', target_object_version_id: 'exact-statement' },
        { relationship_type: 'TARGET', target_object_version_id: 'exact-statement' },
      ],
    },
  });
  expect(list).not.toHaveBeenCalled();
  expect(workspaceList.mock.calls[0]![0]).toMatchObject({
    workspace_id: 'workspace',
    object_id: 'object',
  });
  expect(
    (await screen.findByRole('link', { name: 'Read saved version' })).getAttribute('href'),
  ).toBe('/workspaces/workspace/records/saved');
});

it('offers history but no editing to read-only workspace members', () => {
  render(RecordEdit, {
    props: { record, projectId: 'workspace', canWrite: false },
    context: new Map([[contextKey, { records: {}, query: {} }]]),
  });
  expect(screen.queryByRole('button', { name: 'Edit from this exact version' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Reload visible version history' })).toBeTruthy();
});
