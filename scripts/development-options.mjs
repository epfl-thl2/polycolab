import { parseArgs } from 'node:util';
import net from 'node:net';

export function localOptions(args, env = process.env) {
  const { values } = parseArgs({
    args: args[0] === '--' ? args.slice(1) : args,
    options: {
      'web-port': { type: 'string' },
      'api-port': { type: 'string' },
      'collaboration-port': { type: 'string' },
      'public-origin': { type: 'string' },
    },
  });
  const ports = {};
  const defaults = { web: 5174, api: 8000, collaboration: 8002 };
  const explicitPorts = [];
  for (const name of ['web', 'api', 'collaboration']) {
    const value = values[`${name}-port`] ?? String(defaults[name]);
    if (values[`${name}-port`] !== undefined) explicitPorts.push(name);
    if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 65535)
      throw new Error(`--${name}-port must be an integer between 1 and 65535.`);
    ports[name] = Number(value);
  }
  if (new Set(explicitPorts.map((name) => ports[name])).size !== explicitPorts.length)
    throw new Error('Web, API, and collaboration ports must be different.');
  const origin =
    values['public-origin'] || env.PUBLIC_APP_ORIGIN || `http://localhost:${ports.web}`;
  const url = new URL(origin);
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw new Error(
      '--public-origin must be an HTTP(S) origin without credentials, path, query, or fragment.',
    );
  return {
    ...ports,
    origin: url.origin,
    explicitPorts,
    originConfigured: Boolean(values['public-origin'] || env.PUBLIC_APP_ORIGIN),
  };
}

export async function selectLocalPorts(options, holdUntilStart = false) {
  const reservations = [];
  const selected = { ...options };
  let selectedSuccessfully = false;
  const releasePorts = () =>
    Promise.all(
      reservations.splice(0).map((server) => new Promise((accept) => server.close(accept))),
    );
  async function reserve(port) {
    const server = net.createServer();
    await new Promise((accept, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', accept);
    });
    reservations.push(server);
    return server.address().port;
  }
  try {
    // Reserve explicit ports first so automatic choices cannot take them.
    const names = [
      ...options.explicitPorts,
      ...['web', 'api', 'collaboration'].filter((name) => !options.explicitPorts.includes(name)),
    ];
    for (const name of names) {
      try {
        selected[name] = await reserve(options[name]);
      } catch (error) {
        if (error.code !== 'EADDRINUSE') throw error;
        if (options.explicitPorts.includes(name))
          throw new Error(
            `Port ${options[name]} is occupied. Choose another --${name}-port or omit it for automatic selection.`,
          );
        selected[name] = await reserve(0);
      }
    }
    if (!options.originConfigured) selected.origin = `http://localhost:${selected.web}`;
    selectedSuccessfully = true;
    return { ...selected, releasePorts };
  } finally {
    if (!holdUntilStart || !selectedSuccessfully) await releasePorts();
  }
}
