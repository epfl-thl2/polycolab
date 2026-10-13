import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import net from 'node:net';

const root = fileURLToPath(new URL('../', import.meta.url));
const config = resolve(root, 'deploy/docker/.env');
const mode = process.argv[2];
if (!['local', 'docker', 'apply'].includes(mode))
  throw new Error('Expected local, docker, or apply');
if (!existsSync(config))
  throw new Error('Copy deploy/docker/.env.example to deploy/docker/.env first.');
process.loadEnvFile(config);
const children = new Set();
let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      /* already stopped */
    }
  }
  const timer = setTimeout(() => {
    for (const child of children) {
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch {
        /* already stopped */
      }
    }
  }, 5000);
  timer.unref();
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
function run(executable, args, env = process.env) {
  return new Promise((accept, reject) => {
    const child = spawn(executable, args, { cwd: root, env, stdio: 'inherit', detached: true });
    children.add(child);
    child.on('error', (error) => {
      children.delete(child);
      reject(error);
    });
    child.on('exit', (code, signal) => {
      children.delete(child);
      if (code === 0 || stopping) accept();
      else reject(new Error(`${executable} exited with ${signal || code}`));
    });
  });
}
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
    await checkPort(8000);
    await checkPort(5174);
    const env = {
      ...process.env,
      APP_ENV: 'local',
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
    if (!stopping) {
      const commands = [
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
          'pnpm',
          [
            '--filter',
            '@polycolab/web',
            'run',
            'dev',
            '--host',
            '127.0.0.1',
            '--port',
            '5174',
            '--strictPort',
          ],
        ],
      ];
      console.log('Local mode: http://localhost:5174 — data in .local/');
      await Promise.race(commands.map(([cmd, args]) => run(cmd, args, env)));
      stop();
    }
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
  stop();
}
