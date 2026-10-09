import type { components } from '$lib/api-client';
import { commonsClient, result } from '../lib/commons-client';

export type ApplicationConfiguration = components['schemas']['ApplicationConfiguration'];

export class Capabilities {
  configuration = $state<ApplicationConfiguration>();
  loading = $state(false);
  error = $state(false);

  enabled(name: keyof ApplicationConfiguration): boolean {
    return this.configuration?.[name] === true;
  }

  async load() {
    this.loading = true;
    this.error = false;
    try {
      this.configuration = await result(commonsClient().GET('/api/v1/config'));
    } catch {
      this.configuration = undefined;
      this.error = true;
    } finally {
      this.loading = false;
    }
  }
}
