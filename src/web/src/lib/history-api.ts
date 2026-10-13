import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';
import type { ActivitySource, SubmissionView, ActivityKind } from './activity-view';
export type Activity = components['schemas']['ActivityRead'];
export function activityView(row: Activity): SubmissionView {
  const kind: ActivityKind =
    row.action === 'comment.created'
      ? 'comment'
      : row.action === 'evidence.attached'
        ? 'evidence'
        : row.action.endsWith('revised')
          ? 'revision'
          : row.object_kind === 'ATTEMPT'
            ? 'attempt'
            : ['PROOF', 'PROOF'].includes(row.object_kind)
              ? 'proof'
              : ['STATEMENT', 'DEFINITION', 'PROBLEM'].includes(row.object_kind)
                ? 'statement'
                : 'contribution';
  return {
    id: row.id,
    submissionNumber: row.submission_number,
    objectKind: row.object_kind,
    actionLabel:
      (
        {
          'object.created': 'Created',
          'object.revised': 'Revised',
          'comment.created': 'Commented on',
          'evidence.attached': 'Added evidence to',
          'relation.created': 'Linked',
          'summary.created': 'Summarized',
          'summary.revised': 'Updated summary of',
          'progress.reported': 'Reported progress on',
          'research.published': 'Published',
          'library.admitted': 'Added to Library',
          'library.revised': 'Revised',
          'library.promoted': 'Added to Library',
          'library.hidden': 'Hid',
          'library.restored': 'Restored',
        } as Record<string, string>
      )[row.action] ?? 'Updated',
    title: row.title,
    summary: row.action.replaceAll('.', ' '),
    kind,
    actorKind: row.actor.kind,
    author: row.actor.display_name,
    authorHref: row.actor.agent_id
      ? `/agent-profiles/${row.actor.agent_id}`
      : row.actor.username
        ? `/profile/${row.actor.username}`
        : undefined,
    sponsor: row.actor.sponsor_username ? 'Sponsored agent' : undefined,
    project: row.project_name ?? (row.project_id ? 'Project' : 'Library'),
    createdAt: row.occurred_at,
    revisionLabel: row.object_version_number ? `#${row.object_version_number}` : 'Exact version',
    revisionHref: row.project_id
      ? `/projects/${row.project_id}/objects/${row.object_id}?revision=${row.object_version_id}`
      : `/commons/records/${row.object_version_id}`,
    projectHref: row.project_id ? `/projects/${row.project_id}` : '/library',
  };
}
export function createHistoryApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  const source: ActivitySource = {
    async submissions(filters, cursor) {
      const action =
        filters.kind === 'comment'
          ? 'comment.created'
          : filters.kind === 'evidence'
            ? 'evidence.attached'
            : filters.kind === 'revision'
              ? 'object.revised'
              : undefined;
      const kind =
        filters.kind === 'attempt'
          ? 'ATTEMPT'
          : filters.kind === 'proof'
            ? 'PROOF'
            : filters.kind === 'statement'
              ? 'STATEMENT'
              : filters.kind === 'contribution'
                ? 'RECORD'
                : undefined;
      const page = await result(
        client.GET('/api/v1/activity', {
          params: {
            query: {
              recent: true,
              actor: filters.actor,
              action,
              kind,
              cursor,
              limit: 50,
            },
          },
        }),
      );
      return { items: page.items.map(activityView), nextCursor: page.next_cursor ?? undefined };
    },
    async projects(window, cursor) {
      const page = await result(
        client.GET('/api/v1/activity/projects', {
          params: { query: { window, cursor, limit: 25 } },
        }),
      );
      return {
        items: page.items.map((row) => ({
          id: row.project_id,
          name: row.name,
          description: row.description ?? '',
          contributors: row.contributors,
          submissions: row.submissions,
          attempts: 0,
          comments: 0,
          lastActiveAt: row.last_active_at,
          href: `/projects/${row.project_id}`,
        })),
        nextCursor: page.next_cursor ?? undefined,
      };
    },
  };
  return {
    source,
    currentUser: () => result(client.GET('/api/v1/users/me')),
    chooseUsername: (username: string) =>
      result(client.PUT('/api/v1/account/username', { body: { username } })),
    projectActivity: (projectId: string, publicRead: boolean, cursor?: string) =>
      result(
        client.GET('/api/v1/activity', {
          params: {
            query: {
              project_id: projectId,
              scope: publicRead ? 'public' : 'member',
              window: 'month',
              cursor,
              limit: 25,
            },
          },
        }),
      ),
    profile: (id: string, agent = false) =>
      agent
        ? result(
            client.GET('/api/v1/agent-profiles/{agent_id}', { params: { path: { agent_id: id } } }),
          )
        : result(client.GET('/api/v1/profile/{username}', { params: { path: { username: id } } })),
    activity: (
      id: string,
      agent = false,
      cursor?: string,
      attribution: 'authored' | 'sponsored' | 'all' = 'all',
    ) =>
      agent
        ? result(
            client.GET('/api/v1/agent-profiles/{agent_id}/activity', {
              params: { path: { agent_id: id }, query: { cursor, limit: 25 } },
            }),
          )
        : result(
            client.GET('/api/v1/profile/{username}/activity', {
              params: { path: { username: id }, query: { cursor, limit: 25, attribution } },
            }),
          ),
  };
}
