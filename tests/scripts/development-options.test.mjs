import assert from 'node:assert/strict';
import { test } from 'node:test';
import net from 'node:net';
import { once } from 'node:events';
import { localOptions, selectLocalPorts } from '../../scripts/development-options.mjs';

test('local defaults and overrides keep the browser origin aligned with its port', () => {
  assert.deepEqual(localOptions([], {}), {
    web: 5174,
    api: 8000,
    collaboration: 8002,
    origin: 'http://localhost:5174',
    explicitPorts: [],
    originConfigured: false,
  });
  const args = ['--web-port', '5274', '--api-port=8100', '--collaboration-port', '8102'];
  assert.deepEqual(localOptions(args, {}), {
    web: 5274,
    api: 8100,
    collaboration: 8102,
    origin: 'http://localhost:5274',
    explicitPorts: ['web', 'api', 'collaboration'],
    originConfigured: false,
  });
  assert.equal(
    localOptions(args, { PUBLIC_APP_ORIGIN: 'https://preview.example' }).origin,
    'https://preview.example',
  );
  assert.equal(
    localOptions(['--', ...args, '--public-origin', 'http://localhost:6274/'], {
      PUBLIC_APP_ORIGIN: 'https://preview.example',
    }).origin,
    'http://localhost:6274',
  );
});

for (const args of [
  ['--web-port', '0'],
  ['--api-port', '65536'],
  ['--collaboration-port', '8.5'],
  ['--web-port', '-1'],
  ['--api-port', 'invalid'],
  ['--web-port', '8000', '--api-port', '8000'],
  ['--web-prt', '5274'],
  ['--web-port'],
  ['unexpected'],
  ['--public-origin', 'https://example.com/path'],
  ['--public-origin', 'https://user:secret@example.com'],
  ['--public-origin', 'file:///tmp'],
  ['--public-origin', 'http://localhost:5174/?query=value'],
]) {
  test(`rejects invalid local options: ${args[0]} ${args[1] ?? ''}`, () => {
    assert.throws(() => localOptions(args, {}));
  });
}

test('occupied automatic ports are replaced and the origin follows the selected web port', async (t) => {
  const occupied = net.createServer();
  occupied.listen(0, '127.0.0.1');
  await once(occupied, 'listening');
  t.after(() => new Promise((accept) => occupied.close(accept)));
  const port = occupied.address().port;
  const options = { ...localOptions([], {}), web: port, api: port, collaboration: port };
  const selected = await selectLocalPorts(options);
  assert.equal(new Set([selected.web, selected.api, selected.collaboration, port]).size, 4);
  assert.equal(selected.origin, `http://localhost:${selected.web}`);
  const configured = await selectLocalPorts({
    ...options,
    originConfigured: true,
    origin: 'https://preview.example',
  });
  assert.equal(configured.origin, 'https://preview.example');
  await assert.rejects(selectLocalPorts({ ...options, explicitPorts: ['api'] }), /--api-port/);
  assert.equal(occupied.listening, true);
});

test('free defaults are retained and explicit ports take priority over automatic choices', async () => {
  const server = net.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise((accept) => server.close(accept));
  const options = {
    ...localOptions([], {}),
    web: port,
    api: port,
    collaboration: port,
    explicitPorts: ['api'],
  };
  const selected = await selectLocalPorts(options);
  assert.equal(selected.api, port);
  assert.equal(new Set([selected.web, selected.api, selected.collaboration]).size, 3);
  const retained = await selectLocalPorts({ ...selected, explicitPorts: [] });
  assert.equal(retained.web, selected.web);
  assert.equal(retained.api, selected.api);
  assert.equal(retained.collaboration, selected.collaboration);
});

test('selected ports stay reserved during setup and release on request', async () => {
  const first = await selectLocalPorts(localOptions([], {}), true);
  try {
    await assert.rejects(selectLocalPorts({ ...first, explicitPorts: ['api'] }), /--api-port/);
    const second = await selectLocalPorts({ ...first, explicitPorts: [] });
    assert.notEqual(second.web, first.web);
    assert.notEqual(second.api, first.api);
    assert.notEqual(second.collaboration, first.collaboration);
  } finally {
    await first.releasePorts();
  }
  const reused = await selectLocalPorts({
    ...first,
    explicitPorts: ['web', 'api', 'collaboration'],
  });
  assert.equal(reused.web, first.web);
  await first.releasePorts();
});
