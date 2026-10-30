import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { test } from 'node:test';
import { serviceHealth, waitForReadiness } from '../../scripts/development-health.mjs';

async function endpoint(t, handler) {
  const server = createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => {
    server.closeAllConnections();
    return new Promise((accept) => server.close(accept));
  });
  return [{ name: 'API', url: `http://127.0.0.1:${server.address().port}`, path: '/health/ready' }];
}

test('readiness waits for successful HTTP responses, not just an open port', async (t) => {
  let requests = 0;
  const services = await endpoint(t, (request, response) => {
    assert.equal(request.url, '/health/ready');
    response.writeHead(++requests < 3 ? 503 : 200).end();
  });
  assert.equal(await waitForReadiness(services, { timeoutMs: 2000, pollMs: 10 }), true);
  assert.ok(requests >= 3);
});

test('startup timeout identifies the unhealthy service and HTTP status', async (t) => {
  const services = await endpoint(t, (_request, response) => response.writeHead(503).end());
  await assert.rejects(
    waitForReadiness(services, { timeoutMs: 100, pollMs: 10 }),
    /API \(HTTP 503\)/,
  );
});

test('health checks bound unresponsive connections and shutdown aborts startup', async (t) => {
  const services = await endpoint(t, () => {});
  const health = await serviceHealth(services, undefined, 30);
  assert.equal(health[0].healthy, false);
  assert.match(health[0].detail, /timed out/);
  const controller = new AbortController();
  const pending = waitForReadiness(services, { signal: controller.signal });
  controller.abort();
  assert.equal(await pending, false);
});
