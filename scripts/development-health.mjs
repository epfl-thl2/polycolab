import { setTimeout } from 'node:timers/promises';

export function localServices(ports) {
  return [
    { name: 'API', url: `http://127.0.0.1:${ports.api}`, path: '/health/ready' },
    { name: 'Collaboration', url: `http://127.0.0.1:${ports.collaboration}`, path: '/health/live' },
    { name: 'Website', url: `http://127.0.0.1:${ports.web}`, path: '/' },
  ];
}

export async function serviceHealth(services, signal, requestTimeoutMs = 2000) {
  return Promise.all(
    services.map(async (service) => {
      try {
        const timeout = AbortSignal.timeout(requestTimeoutMs);
        const response = await fetch(`${service.url}${service.path}`, {
          signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
          redirect: 'manual',
        });
        await response.body?.cancel();
        return { ...service, healthy: response.ok, detail: `HTTP ${response.status}` };
      } catch {
        return { ...service, healthy: false, detail: 'unreachable or timed out' };
      }
    }),
  );
}

export async function waitForReadiness(
  services,
  { signal, timeoutMs = 120000, pollMs = 250, requestTimeoutMs = 2000 } = {},
) {
  const deadline = Date.now() + timeoutMs;
  let health = services.map((service) => ({ ...service, healthy: false, detail: 'not checked' }));
  while (!signal?.aborted && Date.now() < deadline) {
    health = await serviceHealth(
      services,
      signal,
      Math.max(1, Math.min(requestTimeoutMs, deadline - Date.now())),
    );
    if (signal?.aborted) return false;
    if (health.every((service) => service.healthy)) return true;
    try {
      await setTimeout(Math.min(pollMs, Math.max(1, deadline - Date.now())), undefined, { signal });
    } catch (error) {
      if (signal?.aborted) return false;
      throw error;
    }
  }
  if (signal?.aborted) return false;
  throw new Error(
    `Startup timed out waiting for ${health
      .filter((service) => !service.healthy)
      .map((service) => `${service.name} (${service.detail})`)
      .join(', ')}. Check the service logs above.`,
  );
}
