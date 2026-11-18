import { readFile } from 'node:fs/promises';
import { resolve, isAbsolute } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);

export async function localController(root, env, apiPort) {
  let settings;
  try {
    settings = JSON.parse(await readFile(resolve(root, '.local/codex-controller.json'), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  if (
    ![settings.python, settings.config].every(
      (value) => typeof value === 'string' && isAbsolute(value),
    )
  )
    throw new Error('.local/codex-controller.json requires absolute python and config paths.');
  const helper = resolve(root, 'scripts/development-controller.py');
  const database = resolve(root, '.local/polycolab.db');
  const { stdout } = await execute(
    settings.python,
    [helper, 'describe', settings.config, '--database', database],
    { env },
  );
  const description = JSON.parse(stdout);
  Object.assign(env, {
    RUNTIME_CODEX_IMAGE: description.image,
    RUNTIME_SANDBOX_BACKEND: description.backend,
    RUNTIME_SANDBOX_VERSION: description.version,
  });
  return {
    command: [
      settings.python,
      [helper, 'run', settings.config, '--api-url', `http://127.0.0.1:${apiPort}`],
    ],
    service: {
      name: 'Codex controller',
      url: `http://127.0.0.1:${apiPort}`,
      async check(signal) {
        const { stdout } = await execute(
          settings.python,
          [
            helper,
            'health',
            settings.config,
            '--database',
            database,
            '--previous-incarnation',
            description.previous,
          ],
          { env, signal, timeout: 2000 },
        );
        return JSON.parse(stdout);
      },
    },
  };
}
