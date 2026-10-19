import type { components } from './api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';
export type DefaultFile = components['schemas']['DefaultFileRead'];
export type DefaultFiles = components['schemas']['DefaultFilesRead'];
export type DefaultFileCommand = components['schemas']['DefaultFileCommand'];
export function createDefaultFilesApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
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
