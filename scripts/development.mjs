import { createSupervisor } from './development-processes.mjs';
import {
  controlSocketPath,
  listenForStop,
  requestStatus,
  requestStop,
} from './development-control.mjs';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { localServices, serviceHealth, waitForReadiness } from './development-health.mjs';
import { localOptions, selectLocalPorts } from './development-options.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const config = resolve(root, 'deploy/docker/.env');
const mode = process.argv[2];
if (!['local', 'docker', 'apply', 'stop', 'status'].includes(mode))
  throw new Error('Expected local, docker, apply, stop, or status');
if (process.argv.includes('--help')) {
  console.log(
    'Usage: pnpm run dev:local [--web-port 5174] [--api-port 8000] [--collaboration-port 8002] [--public-origin http://localhost:5174]',
  );
  console.log(
    'Unspecified ports use the defaults when free, or automatically select a free alternative.',
  );
  process.exit(0);
}
if (mode !== 'local' && process.argv.length > 3)
  throw new Error('Port and origin options are only supported by dev:local.');
const socketPath = await controlSocketPath(root);
if (mode === 'stop') {
  // Keep stop usable for launchers started before the runtime-path change.
  const stopped =
    (await requestStop(socketPath)) ||
    (await requestStop(resolve(root, '.local/development.sock')));
  console.log(
    stopped ? 'Local services stopped.' : 'No local launcher is running for this checkout.',
  );
  process.exit(0);
}
if (mode === 'status') {
  const status = await requestStatus(socketPath);
  if (!status) console.log('No local launcher is running for this checkout.');
  else {
    console.log(`Local mode: ${status.phase} (launcher PID ${status.pid})`);
    if (status.origin) console.log(`Browser: ${status.origin}`);
    for (const service of status.services)
      console.log(
        `  ${service.name}: ${service.healthy ? 'healthy' : service.detail} — ${service.url}`,
      );
  }
  process.exit(0);
}
if (!existsSync(config))
  throw new Error('Copy deploy/docker/.env.example to deploy/docker/.env first.');
process.loadEnvFile(config);
const supervisor = createSupervisor({ cwd: root });
const run = supervisor.run;
const readiness = new AbortController();
let phase = 'preparing';
let services = [];
let origin;
const stop = () => {
  phase = 'stopping';
  readiness.abort();
  return supervisor.stop();
};
async function status() {
  const health =
    phase === 'preparing'
      ? services.map((service) => ({ ...service, healthy: false, detail: 'waiting for setup' }))
      : await serviceHealth(services, readiness.signal);
  return {
    pid: process.pid,
    origin,
    phase: phase === 'ready' && health.some((service) => !service.healthy) ? 'degraded' : phase,
    services: health,
  };
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
let closeControl;
let releasePorts;

try {
  if (mode !== 'local') {
    const env = {
      ...process.env,
      PUBLIC_APP_ORIGIN: process.env.PUBLIC_APP_ORIGIN || 'http://localhost:8000',
    };
    await run(
      'bash',
      [
        resolve(root, 'deploy/scripts/deploy-stack.sh'),
        mode === 'apply' ? 'reuse' : 'build',
        '--env-file',
        config,
        '-f',
        resolve(root, 'deploy/docker/compose.yml'),
      ],
      env,
    );
  } else {
    const options = localOptions(process.argv.slice(3));
    closeControl = await listenForStop(socketPath, stop, status);
    const ports = await selectLocalPorts(options, true);
    releasePorts = ports.releasePorts;
    services = localServices(ports);
    origin = ports.origin;
    console.log(`Preparing local mode: ${origin}`);
    const env = {
      ...process.env,
      APP_ENV: 'local',
      COLLABORATION_URL: `http://127.0.0.1:${ports.collaboration}`,
      COLLABORATION_PORT: String(ports.collaboration),
      COLLABORATION_HOST: '127.0.0.1',
      COLLABORATION_TOKEN:
        process.env.COLLABORATION_TOKEN ||
        'polycolab-local-collaboration-token-change-in-production',
      DATABASE_URL: `sqlite+pysqlite:///${resolve(root, '.local/polycolab.db')}`,
      ARTIFACT_LOCAL_DIRECTORY: resolve(root, '.local/artifacts'),
      PROJECT_REPOSITORY_DIRECTORY: resolve(root, '.local/repositories'),
      PUBLIC_APP_ORIGIN: ports.origin,
      ALLOWED_ORIGINS: JSON.stringify([
        ...new Set([
          ports.origin,
          `http://localhost:${ports.web}`,
          `http://127.0.0.1:${ports.web}`,
        ]),
      ]),
      POLYCOLAB_API_PROXY_TARGET: `http://127.0.0.1:${ports.api}`,
      // Cookies are shared across ports on a hostname; separate local login sessions.
      LOCAL_AUTH_COOKIE_NAME:
        process.env.LOCAL_AUTH_COOKIE_NAME ||
        (ports.web === 5174 ? 'polycolab_session' : `polycolab_session_${ports.web}`),
    };
    await run(
      'uv',
      [
        'run',
        '--directory',
        'src/backend',
        'python',
        '-m',
        'polycolab.operations.local_development',
      ],
      env,
    );
    await run(
      process.execPath,
      ['node_modules/@sveltejs/kit/svelte-kit.js', 'sync'],
      env,
      resolve(root, 'src/web'),
    );
    if (!supervisor.stopping) {
      await releasePorts();
      // Launch Node entry points directly so package-manager subprocesses cannot
      // move services outside the process groups owned by this launcher.
      const commands = [
        [
          process.execPath,
          ['--experimental-strip-types', 'src/server.ts'],
          resolve(root, 'src/collaboration'),
        ],
        [
          'uv',
          [
            'run',
            '--directory',
            'src/backend',
            'uvicorn',
            'polycolab.main:app',
            '--reload',
            '--host',
            '127.0.0.1',
            '--port',
            String(ports.api),
          ],
        ],
        [
          process.execPath,
          [
            'node_modules/vite/bin/vite.js',
            '--host',
            '127.0.0.1',
            '--port',
            String(ports.web),
            '--strictPort',
          ],
          resolve(root, 'src/web'),
        ],
      ];
      phase = 'starting';
      console.log('Starting services; waiting for API, collaboration, and website readiness…');
      const names = ['Collaboration', 'API', 'Website'];
      const exited = Promise.race(
        commands.map(async ([cmd, args, directory], index) => {
          try {
            await run(cmd, args, env, directory);
            if (!supervisor.stopping) throw new Error('process exited unexpectedly');
          } catch (error) {
            throw new Error(`${names[index]}: ${error.message}`);
          }
        }),
      );
      const ready = await Promise.race([
        exited,
        waitForReadiness(services, { signal: readiness.signal }),
      ]);
      if (ready && !supervisor.stopping) {
        phase = 'ready';
        console.log(
          `Ready: ${origin} — API :${ports.api}, collaboration :${ports.collaboration} — data in .local/`,
        );
      }
      await exited;
      await stop();
    }
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
  await stop();
} finally {
  if (releasePorts) await releasePorts();
  await stop();
  if (closeControl) await closeControl();
}
