import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { localController } from '../../scripts/development-controller.mjs';
import { serviceHealth } from '../../scripts/development-health.mjs';
import { createSupervisor } from '../../scripts/development-processes.mjs';

test('configured controller follows selected API port, readiness and supervised shutdown', async (t) => {
  const root = await mkdtemp(resolve(tmpdir(), 'polycolab-controller-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  assert.equal(await localController(root, {}, 12345), null);
  await mkdir(resolve(root, '.local'));
  await mkdir(resolve(root, 'scripts'));
  await writeFile(
    resolve(root, '.local/codex-controller.json'),
    JSON.stringify({ python: process.execPath, config: '/prepared/controller.toml' }),
  );
  await writeFile(
    resolve(root, 'scripts/development-controller.py'),
    `
const fs = require('fs');
const action = process.argv[2];
if (action === 'describe') console.log(JSON.stringify({image:'codex@sha256:test',backend:'microsandbox',version:'0.6.18',previous:'old'}));
if (action === 'health') {
  if (!process.argv.includes('old')) process.exit(1);
  console.log(JSON.stringify({healthy:fs.existsSync('ready'),detail:'waiting for controller readiness'}));
}
if (action === 'run') {
  if (!process.argv.includes('http://127.0.0.1:12345')) process.exit(1);
  fs.writeFileSync('ready', String(process.pid));
  process.on('SIGTERM', () => { fs.unlinkSync('ready'); process.exit(0); });
  setInterval(() => {},1000);
}
`,
  );
  // The helper uses the launcher's working directory, just like the real local stack.
  const previous = process.cwd();
  process.chdir(root);
  t.after(() => process.chdir(previous));
  const env = { ...process.env };
  const controller = await localController(root, env, 12345);
  assert.equal(env.RUNTIME_CODEX_IMAGE, 'codex@sha256:test');
  assert.equal((await serviceHealth([controller.service]))[0].healthy, false);
  const supervisor = createSupervisor({ cwd: root, stdio: 'ignore' });
  t.after(() => supervisor.stop());
  const running = supervisor.run(...controller.command, env);
  const { waitForReadiness } = await import('../../scripts/development-health.mjs');
  await waitForReadiness([controller.service], { timeoutMs: 3000 });
  await supervisor.stop();
  await running;
  assert.equal((await serviceHealth([controller.service]))[0].healthy, false);
});
