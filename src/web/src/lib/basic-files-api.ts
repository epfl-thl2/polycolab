import type { components } from './api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';
export type BasicFile = components['schemas']['BasicFileRead'];
export type BasicFiles = components['schemas']['BasicFilesRead'];
export type BasicFileCommand = components['schemas']['BasicFileCommand'];
export function createBasicFilesApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  return {
    list: (project_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/files', { params: { path: { project_id } } }),
      ),
    command: (project_id: string, body: BasicFileCommand) =>
      result(
        client.POST('/api/v1/projects/{project_id}/files', {
          params: { path: { project_id } },
          body,
        }),
      ),
  };
}
