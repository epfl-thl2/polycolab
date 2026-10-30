import net from 'node:net';
import { chmod, lstat, mkdir, realpath, rmdir, unlink } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { createHash } from 'node:crypto';

export async function controlSocketPath(root) {
  // /tmp stays short even when TMPDIR or the checkout path is deeply nested.
  const directory = `/tmp/polycolab-dev-${process.getuid()}`;
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  if (!info.isDirectory() || info.uid !== process.getuid() || info.mode & 0o077)
    throw new Error(`Expected a private runtime directory at ${directory}`);
  const key = createHash('sha256')
    .update(await realpath(root))
    .digest('hex')
    .slice(0, 32);
  return join(directory, `${key}.sock`);
}

async function requestControl(path, command) {
  return new Promise((accept, reject) => {
    const socket = net.createConnection(path);
    let response = '';
    socket.setTimeout(15000, () => socket.destroy(new Error('Local control request timed out.')));
    socket.on('connect', () => socket.write(`${command}\n`));
    socket.on('data', (data) => {
      response += data;
      if (response.length > 16384) socket.destroy(new Error('Invalid local control response.'));
    });
    socket.on('end', () => {
      if (response) accept(response);
      else
        reject(
          new Error(
            'Launcher did not support or complete this request. Restart dev:local to load the current launcher.',
          ),
        );
    });
    socket.on('error', (error) => {
      if (['ENOENT', 'ECONNREFUSED'].includes(error.code)) accept(null);
      else reject(error);
    });
  });
}

export async function requestStop(path) {
  const response = await requestControl(path, 'stop');
  if (response === null) return false;
  if (response !== 'stopped\n') throw new Error('Local launcher did not confirm shutdown.');
  return true;
}

export async function requestStatus(path) {
  const response = await requestControl(path, 'status');
  return response === null ? null : JSON.parse(response);
}

export async function listenForStop(
  path,
  stop,
  status = async () => ({ phase: 'unknown', services: [] }),
) {
  await mkdir(dirname(path), { recursive: true });
  const lock = `${path}.lock`;
  try {
    await mkdir(lock, { mode: 0o700 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    throw new Error(
      `Local mode is already running or starting. If startup was interrupted, ensure no launcher is starting before removing ${lock}.`,
    );
  }
  try {
    return await bindControl(path, stop, status);
  } finally {
    await rmdir(lock);
  }
}

async function bindControl(path, stop, status) {
  // The exclusive startup lock covers probing, stale cleanup, and binding.
  // Probe an existing socket without sending a stop request to a running launcher.
  const active = await new Promise((accept, reject) => {
    const probe = net.createConnection(path);
    probe.on('connect', () => {
      probe.destroy();
      accept(true);
    });
    probe.on('error', (error) => {
      if (['ENOENT', 'ECONNREFUSED'].includes(error.code)) accept(false);
      else reject(error);
    });
  });
  if (active) throw new Error('Local mode is already running. Use pnpm run dev:stop first.');
  try {
    if (!(await lstat(path)).isSocket()) throw new Error(`Expected a socket at ${path}`);
    await unlink(path);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const server = net.createServer((socket) => {
    socket.setEncoding('utf8');
    socket.setTimeout(15000, () => socket.destroy());
    socket.on('error', () => socket.destroy());
    let request = '';
    let handled = false;
    socket.on('data', async (data) => {
      if (handled) return socket.destroy();
      request += data;
      const commands = ['stop\n', 'status\n'];
      if (request.length > 7 || !commands.some((command) => command.startsWith(request)))
        return socket.destroy();
      if (!commands.includes(request)) return;
      handled = true;
      try {
        if (request === 'status\n') socket.end(`${JSON.stringify(await status())}\n`);
        else {
          await stop();
          socket.end('stopped\n');
        }
      } catch {
        socket.destroy();
      }
    });
  });
  await new Promise((accept, reject) => {
    server.once('error', reject);
    server.listen(path, accept);
  });
  try {
    await chmod(path, 0o600);
  } catch (error) {
    server.close();
    throw error;
  }
  return () =>
    new Promise((accept, reject) => server.close((error) => (error ? reject(error) : accept())));
}
