import assert from 'node:assert/strict';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, cp, writeFile, readFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { test } from 'node:test';
import { createSupervisor } from '../../scripts/development-processes.mjs';
import {
  controlSocketPath,
  listenForStop,
  requestStop,
  requestStatus,
} from '../../scripts/development-control.mjs';

async function until(check) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await setTimeout(25);
  }
  throw new Error('Timed out waiting for process state');
}
async function running(pid) {
  if (process.platform !== 'linux') {
    try {
      process.kill(pid, 0);
      return true;
    } catch (error) {
      if (error.code === 'ESRCH') return false;
      throw error;
    }
  }
  // Linux may retain an orphan as a zombie until its container init reaps it.
  try {
    const stat = await readFile(`/proc/${pid}/stat`, 'utf8');
    return stat.slice(stat.lastIndexOf(')') + 2, stat.lastIndexOf(')') + 3) !== 'Z';
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

test('shutdown kills a stubborn descendant after its wrapper has exited', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-processes-'));
  const supervisor = createSupervisor({ cwd: directory, graceMs: 150, stdio: 'ignore' });
  t.after(async () => {
    await supervisor.stop();
    await rm(directory, { recursive: true, force: true });
  });
  const descendant = `process.on('SIGTERM', () => {}); require('fs').writeFileSync('pid', String(process.pid)); setInterval(() => {}, 1000);`;
  await supervisor.run(process.execPath, [
    '-e',
    `const c = require('child_process').spawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], {stdio: 'ignore'}); c.unref();`,
  ]);
  let pid;
  await until(async () => {
    try {
      pid = Number(await readFile(resolve(directory, 'pid'), 'utf8'));
      return true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      return false;
    }
  });
  assert.equal(await running(pid), true);
  await supervisor.stop();
  await until(async () => !(await running(pid)));
});

test('stop control is scoped to its socket and rejects duplicate launchers', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-control-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const socket = resolve(directory, 'dev.sock');
  assert.equal(await requestStop(socket), false);
  assert.equal(await requestStatus(socket), null);
  let stopped = false;
  const close = await listenForStop(socket, async () => {
    stopped = true;
  });
  t.after(close);
  await assert.rejects(
    listenForStop(socket, async () => {}),
    /already running/,
  );
  assert.equal(stopped, false);
  assert.equal(await requestStop(socket), true);
  assert.equal(stopped, true);
});

let nextTestPort = 20000;

test(
  'checkouts run concurrently with explicit and automatic ports',
  { concurrency: true },
  async (suite) => {
    await Promise.all(
      ['SIGINT', 'command', 'automatic', 'cancel-startup', 'service-exit'].map((method) =>
        suite.test(
          `local launcher stops all services via ${method}`,
          { timeout: 20000 },
          async (t) => {
            const parent = await mkdtemp(resolve(tmpdir(), 'polycolab-launcher-'));
            const directory =
              method === 'command' ? resolve(parent, 'long-checkout-'.repeat(12)) : parent;
            await mkdir(directory, { recursive: true });
            await cp(new URL('../../scripts/', import.meta.url), resolve(directory, 'scripts'), {
              recursive: true,
            });
            const reservations = await Promise.all(
              [0, 1, 2].map(async () => {
                // Keep explicit fixture ports outside the ephemeral range used by
                // automatic selection and HTTP clients in concurrent test processes.
                while (nextTestPort < 30000) {
                  const server = net.createServer();
                  server.listen(nextTestPort++, '127.0.0.1');
                  try {
                    await once(server, 'listening');
                    return server;
                  } catch (error) {
                    if (error.code !== 'EADDRINUSE') throw error;
                  }
                }
                throw new Error('No free fixture port');
              }),
            );
            let [webPort, apiPort, collaborationPort] = reservations.map(
              (server) => server.address().port,
            );
            await Promise.all(
              reservations.map((server) => new Promise((accept) => server.close(accept))),
            );
            await mkdir(resolve(directory, 'deploy/docker'), { recursive: true });
            await mkdir(resolve(directory, 'bin'));
            await writeFile(resolve(directory, 'deploy/docker/.env'), 'REGISTRATION_MODE=open\n');
            const unready = resolve(directory, 'unready');
            if (['command', 'cancel-startup'].includes(method)) await writeFile(unready, 'wait');
            // Replace only the service commands; exercise the real launcher and stop CLI.
            const fake = `#!${process.execPath}
const fs = require('fs');
if (process.argv.includes('polycolab.operations.local_development')) process.exit(0);
fs.appendFileSync(${JSON.stringify(resolve(directory, 'configuration'))}, JSON.stringify({ pid: process.pid, args: process.argv, origin: process.env.PUBLIC_APP_ORIGIN, allowed: JSON.parse(process.env.ALLOWED_ORIGINS), proxy: process.env.POLYCOLAB_API_PROXY_TARGET, collaboration: process.env.COLLABORATION_URL, cookie: process.env.LOCAL_AUTH_COOKIE_NAME }) + '\\n');
const port = process.argv.includes('--port') ? Number(process.argv[process.argv.indexOf('--port') + 1]) : Number(process.env.COLLABORATION_PORT);
require('http').createServer((_request, response) => {
  response.writeHead(fs.existsSync(${JSON.stringify(resolve(directory, 'unready'))}) ? 503 : 200).end('test service');
}).listen(port, process.env.COLLABORATION_HOST, () => {
  fs.appendFileSync(${JSON.stringify(resolve(directory, 'services'))}, String(process.pid) + '\\n');
});
process.on('SIGTERM', () => { if (!process.argv[1].endsWith('/uv')) process.exit(0); });
setInterval(() => {}, 1000);
`;
            await writeFile(resolve(directory, 'bin/uv'), fake, { mode: 0o755 });
            for (const path of [
              'src/collaboration/src/server.ts',
              'src/web/node_modules/vite/bin/vite.js',
              'src/web/node_modules/@sveltejs/kit/svelte-kit.js',
            ]) {
              const target = resolve(directory, path);
              await mkdir(resolve(target, '..'), { recursive: true });
              await writeFile(target, path.endsWith('svelte-kit.js') ? '' : fake);
            }
            const launcher = spawn(
              process.execPath,
              [
                'scripts/development.mjs',
                'local',
                ...(method === 'automatic'
                  ? []
                  : [
                      '--web-port',
                      String(webPort),
                      '--api-port',
                      String(apiPort),
                      '--collaboration-port',
                      String(collaborationPort),
                      '--public-origin',
                      `http://localhost:${webPort}`,
                    ]),
              ],
              {
                cwd: directory,
                env: {
                  ...process.env,
                  LOCAL_AUTH_COOKIE_NAME: '',
                  PUBLIC_APP_ORIGIN: '',
                  PATH: `${directory}/bin:${process.env.PATH}`,
                },
                stdio: ['ignore', 'pipe', 'pipe'],
              },
            );
            let output = '';
            launcher.stdout.on('data', (data) => {
              output += data;
            });
            launcher.stderr.on('data', (data) => {
              output += data;
            });
            const exited = once(launcher, 'exit');
            let pids = [];
            t.after(async () => {
              if (launcher.exitCode === null) launcher.kill('SIGTERM');
              await exited;
              for (const pid of pids) {
                try {
                  process.kill(-pid, 'SIGKILL');
                } catch {}
              }
              await rm(parent, { recursive: true, force: true });
            });
            await until(async () => {
              if (launcher.exitCode !== null) throw new Error(output);
              try {
                pids = (await readFile(resolve(directory, 'services'), 'utf8'))
                  .trim()
                  .split('\n')
                  .map(Number);
                return pids.length === 3;
              } catch (error) {
                if (error.code !== 'ENOENT') throw error;
                return false;
              }
            });
            const configurations = (await readFile(resolve(directory, 'configuration'), 'utf8'))
              .trim()
              .split('\n')
              .map((line) => JSON.parse(line));
            assert.equal(configurations.length, 3);
            if (method === 'automatic') {
              webPort = Number(new URL(configurations[0].origin).port);
              apiPort = Number(new URL(configurations[0].proxy).port);
              collaborationPort = Number(new URL(configurations[0].collaboration).port);
              assert.equal(new Set([webPort, apiPort, collaborationPort]).size, 3);
              assert.ok([webPort, apiPort, collaborationPort].every((port) => port > 0));
            }
            for (const config of configurations) {
              assert.equal(config.origin, `http://localhost:${webPort}`);
              assert.ok(config.allowed.includes(config.origin));
              assert.equal(config.proxy, `http://127.0.0.1:${apiPort}`);
              assert.equal(config.collaboration, `http://127.0.0.1:${collaborationPort}`);
              assert.equal(
                config.cookie,
                webPort === 5174 ? 'polycolab_session' : `polycolab_session_${webPort}`,
              );
            }
            assert.ok(configurations.some((config) => config.args.includes(String(apiPort))));
            assert.ok(configurations.some((config) => config.args.includes(String(webPort))));
            const socket = await controlSocketPath(directory);
            if (['command', 'cancel-startup'].includes(method)) {
              assert.equal(output.includes('Ready:'), false);
              const pending = await requestStatus(socket);
              assert.equal(pending.phase, 'starting');
              assert.equal(
                pending.services.every((service) => !service.healthy),
                true,
              );
              if (method === 'command') await rm(unready);
            }
            if (method !== 'cancel-startup') {
              await until(() => output.includes('Ready:'));
              const healthy = await requestStatus(socket);
              assert.equal(healthy.phase, 'ready');
              assert.equal(healthy.origin, `http://localhost:${webPort}`);
              assert.equal(healthy.services.length, 3);
              assert.equal(
                healthy.services.every((service) => service.healthy),
                true,
              );
            }
            if (method === 'command') {
              const statusCli = spawn(process.execPath, ['scripts/development.mjs', 'status'], {
                cwd: directory,
                stdio: 'pipe',
              });
              let text = '';
              statusCli.stdout.on('data', (data) => {
                text += data;
              });
              assert.equal((await once(statusCli, 'exit'))[0], 0);
              assert.match(text, /Local mode: ready/);
              assert.ok(text.includes(`Browser: http://localhost:${webPort}`));
              assert.match(text, /API: healthy/);
              await writeFile(unready, 'unhealthy');
              assert.equal((await requestStatus(socket)).phase, 'degraded');
            }
            if (method === 'service-exit') {
              const api = configurations.find((config) => config.args.includes(String(apiPort)));
              process.kill(api.pid, 'SIGKILL');
            } else if (method === 'SIGINT') launcher.kill('SIGINT');
            else {
              const stop = spawn(process.execPath, ['scripts/development.mjs', 'stop'], {
                cwd: directory,
                stdio: 'pipe',
              });
              assert.equal((await once(stop, 'exit'))[0], 0);
            }
            assert.equal((await exited)[0], method === 'service-exit' ? 1 : 0, output);
            if (method === 'service-exit') assert.match(output, /API:.*SIGKILL/);
            if (method === 'cancel-startup') assert.equal(output.includes('Ready:'), false);
            for (const pid of pids) await until(async () => !(await running(pid)));
            assert.equal(await requestStop(await controlSocketPath(directory)), false);
          },
        ),
      ),
    );
  },
);

test(
  'real collaboration server releases its port across repeated launches',
  { timeout: 20000 },
  async (t) => {
    const reservation = net.createServer();
    reservation.listen(0, '127.0.0.1');
    await once(reservation, 'listening');
    const port = reservation.address().port;
    await new Promise((accept) => reservation.close(accept));
    for (let attempt = 0; attempt < 2; attempt++) {
      const supervisor = createSupervisor({
        cwd: fileURLToPath(new URL('../../src/collaboration/', import.meta.url)),
        stdio: 'ignore',
      });
      t.after(() => supervisor.stop());
      let failure;
      const exited = supervisor
        .run(process.execPath, ['--experimental-strip-types', 'src/server.ts'], {
          ...process.env,
          COLLABORATION_PORT: String(port),
          COLLABORATION_TOKEN: 'test-collaboration-token-at-least-32-characters',
        })
        .catch((error) => {
          failure = error;
        });
      await until(async () => {
        if (failure) throw failure;
        try {
          return (await fetch(`http://127.0.0.1:${port}/health/live`)).ok;
        } catch {
          return false;
        }
      });
      await supervisor.stop();
      await exited;
      assert.equal(failure, undefined);
      const probe = net.createServer();
      probe.listen(port, '127.0.0.1');
      await once(probe, 'listening');
      await new Promise((accept) => probe.close(accept));
    }
  },
);

test('concurrent starts preserve exactly one reachable owner', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-race-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = resolve(directory, 'control.sock');
  for (let trial = 0; trial < 100; trial++) {
    const stopped = [];
    const results = await Promise.allSettled(
      [0, 1].map((id) =>
        listenForStop(path, async () => {
          stopped.push(id);
        }),
      ),
    );
    const winners = results.filter((result) => result.status === 'fulfilled');
    try {
      assert.equal(winners.length, 1);
      assert.equal(results.filter((result) => result.status === 'rejected').length, 1);
      assert.equal(await requestStop(path), true);
      assert.deepEqual(stopped, [results.findIndex((result) => result.status === 'fulfilled')]);
    } finally {
      await Promise.all(winners.map((result) => result.value()));
    }
  }
});

test('control paths are short, canonical and distinct between checkouts', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-path-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const root = resolve(directory, 'long-checkout-'.repeat(12));
  await mkdir(root);
  const alias = resolve(directory, 'alias');
  await symlink(root, alias);
  const path = await controlSocketPath(root);
  assert.ok(Buffer.byteLength(path) < 100);
  assert.equal(await controlSocketPath(alias), path);
  assert.notEqual(await controlSocketPath(directory), path);
  const close = await listenForStop(path, async () => {});
  try {
    assert.equal(await requestStop(path), true);
  } finally {
    await close();
  }
});

test('fragmented stop requests work and malformed requests do not stop services', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-framing-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = resolve(directory, 'control.sock');
  let stops = 0;
  const close = await listenForStop(path, async () => {
    stops++;
  });
  t.after(close);
  for (const invalid of ['stop'.repeat(100), 'start\n']) {
    const socket = net.createConnection(path);
    await once(socket, 'connect');
    const ended = once(socket, 'close');
    socket.end(invalid);
    await ended;
    assert.equal(stops, 0);
  }
  const socket = net.createConnection(path);
  let reply = '';
  socket.on('data', (chunk) => {
    reply += chunk;
  });
  await once(socket, 'connect');
  const ended = once(socket, 'close');
  for (const part of ['st', 'op', '\n']) {
    socket.write(part);
    await setTimeout(20);
  }
  await ended;
  assert.equal(reply, 'stopped\n');
  assert.equal(stops, 1);
});

test('stale sockets recover and failed binds release the startup lock', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-stale-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = resolve(directory, 'control.sock');
  await writeFile(path, 'not a socket');
  await assert.rejects(
    listenForStop(path, async () => {}),
    /Expected a socket/,
  );
  assert.equal(await readFile(path, 'utf8'), 'not a socket');
  await rm(path);
  const child = spawn(process.execPath, [
    '-e',
    "require('net').createServer().listen(process.argv[1], () => process.exit(0))",
    path,
  ]);
  assert.equal((await once(child, 'exit'))[0], 0);
  const close = await listenForStop(path, async () => {});
  try {
    assert.equal(await requestStop(path), true);
  } finally {
    await close();
  }
});

test('stop CLI still reaches a launcher using the previous socket location', async (t) => {
  const directory = await mkdtemp(resolve(tmpdir(), 'polycolab-legacy-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await cp(new URL('../../scripts/', import.meta.url), resolve(directory, 'scripts'), {
    recursive: true,
  });
  let stopped = false;
  const close = await listenForStop(resolve(directory, '.local/development.sock'), async () => {
    stopped = true;
  });
  t.after(close);
  const child = spawn(process.execPath, ['scripts/development.mjs', 'stop'], {
    cwd: directory,
    stdio: 'pipe',
  });
  assert.equal((await once(child, 'exit'))[0], 0);
  assert.equal(stopped, true);
});
