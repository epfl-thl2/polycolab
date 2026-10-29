import { createSupervisor } from './development-processes.mjs';
import { controlSocketPath, listenForStop, requestStop } from './development-control.mjs';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import net from 'node:net';

const root = fileURLToPath(new URL('../', import.meta.url));
const config = resolve(root, 'deploy/docker/.env');
const mode = process.argv[2];
if (!['local', 'docker', 'apply', 'stop'].includes(mode))
  throw new Error('Expected local, docker, apply, or stop');
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
if (!existsSync(config))
  throw new Error('Copy deploy/docker/.env.example to deploy/docker/.env first.');
process.loadEnvFile(config);
const supervisor = createSupervisor({ cwd: root });
const run = supervisor.run;
const stop = () => supervisor.stop();
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
let closeControl;
async function checkPort(port) {
  await new Promise((accept, reject) => {
    const server = net.createServer();
    server.once('error', () =>
      reject(
        new Error(
          `Port ${port} is occupied. Stop the other deployment before starting local mode.`,
        ),
      ),
    );
    server.listen(port, '127.0.0.1', () => server.close(accept));
  });
}
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
    closeControl = await listenForStop(socketPath, stop);
    await checkPort(8000);
    await checkPort(8002);
    await checkPort(5174);
    const env = {
      ...process.env,
      APP_ENV: 'local',
      COLLABORATION_URL: 'http://127.0.0.1:8002',
      COLLABORATION_TOKEN:
        process.env.COLLABORATION_TOKEN ||
        'polycolab-local-collaboration-token-change-in-production',
      DATABASE_URL: `sqlite+pysqlite:///${resolve(root, '.local/polycolab.db')}`,
      ARTIFACT_LOCAL_DIRECTORY: resolve(root, '.local/artifacts'),
      PROJECT_REPOSITORY_DIRECTORY: resolve(root, '.local/repositories'),
      PUBLIC_APP_ORIGIN: process.env.PUBLIC_APP_ORIGIN || 'http://localhost:5174',
      ALLOWED_ORIGINS: JSON.stringify(['http://localhost:5174', 'http://127.0.0.1:5174']),
      POLYCOLAB_API_PROXY_TARGET: 'http://127.0.0.1:8000',
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
            '8000',
          ],
        ],
        [
          process.execPath,
          [
            'node_modules/vite/bin/vite.js',
            '--host',
            '127.0.0.1',
            '--port',
            '5174',
            '--strictPort',
          ],
          resolve(root, 'src/web'),
        ],
      ];
      console.log('Local mode: http://localhost:5174 — data in .local/');
      await Promise.race(commands.map(([cmd, args, directory]) => run(cmd, args, env, directory)));
      await stop();
    }
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
  await stop();
} finally {
  await stop();
  if (closeControl) await closeControl();
}
