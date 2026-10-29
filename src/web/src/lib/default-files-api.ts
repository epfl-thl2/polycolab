import type { components } from './api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';
export type DefaultFile = components['schemas']['DefaultFileRead'];
export type DefaultFiles = components['schemas']['DefaultFilesRead'];
export type DefaultFileCommand = components['schemas']['DefaultFileCommand'];
export function createDefaultFilesApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  return {
    list: (project_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/files', { params: { path: { project_id } } }),
      ),
    command: (project_id: string, body: DefaultFileCommand) =>
      result(
        client.POST('/api/v1/projects/{project_id}/files', {
          params: { path: { project_id } },
          body,
        }),
      ),
  };
}
