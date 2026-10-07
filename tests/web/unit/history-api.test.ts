import { expect, it } from 'vitest';
import { activityView, type Activity } from '../../../web/src/lib/history-api';

it('maps activity to its exact object version in public and workspace views', () => {
  const event: Activity = {
    id: 'event',
    submission_number: 1,
    contribution_id: null,
    action: 'object.revised',
    actor: { kind: 'human', display_name: 'Ada' },
    object_id: 'object',
    object_version_id: 'version-2',
    previous_object_version_id: 'version-1',
    title: 'Statement',
    excerpt_md: 'Formulation',
    object_kind: 'STATEMENT',
    workspace_id: null,
    occurred_at: '2026-09-15T12:00:00Z',
    reconstructed: false,
  };
  expect(activityView(event).revisionHref).toBe('/commons/records/version-2');
  expect(activityView(event).revisionLabel).toBe('Exact version');
  expect(activityView({ ...event, workspace_id: 'workspace' }).revisionHref).toBe(
    '/workspaces/workspace/objects/object?revision=version-2',
  );
});
