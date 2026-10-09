import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export function createCommunityApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    get: (entryId: string) =>
      result(
        client.GET('/api/v1/community/{entry_id}/me', { params: { path: { entry_id: entryId } } }),
      ),
    interestCount: (entryId: string) =>
      result(
        client.GET('/api/v1/community/{entry_id}', {
          params: { path: { entry_id: entryId } },
        }),
      ),
    follow: (entryId: string, active: boolean) =>
      result(
        client.PUT('/api/v1/community/{entry_id}/follow', {
          params: { path: { entry_id: entryId } },
          body: { active },
        }),
      ),
    interest: (entryId: string, active: boolean) =>
      result(
        client.PUT('/api/v1/community/{entry_id}/interest', {
          params: { path: { entry_id: entryId } },
          body: { active },
        }),
      ),
    notifications: (cursor?: string) =>
      result(client.GET('/api/v1/notifications', { params: { query: { cursor } } })),
    summary: (entryId: string) =>
      result(
        client.GET('/api/v1/community/{entry_id}/summary', {
          params: { path: { entry_id: entryId } },
        }),
      ),
  };
}
