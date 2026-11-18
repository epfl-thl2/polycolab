import type { components } from './api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';

export type ResearchMessage = components['schemas']['ResearchHelperMessage'];

export function createResearchHelperApi(options: AuthenticatedClientOptions) {
  const client = authenticatedClient(options);
  return {
    ask: (messages: ResearchMessage[], signal?: AbortSignal, modelId?: string) =>
      result(
        client.POST('/api/v1/research-helper/messages', {
          body: { messages, ...(modelId ? { model_id: modelId } : {}) },
          signal,
        }),
      ),
  };
}
