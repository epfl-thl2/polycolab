import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { brandTokensSource, syncBrandTokens } from './sync-brand.mjs';

const repositoryRoot = fileURLToPath(new URL('../', import.meta.url));

async function availablePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  const port = typeof address === 'object' && address ? address.port : undefined;
  await new Promise((resolve) => server.close(resolve));
  if (!port) throw new Error('Could not allocate a documentation preview port.');
  return port;
}

async function waitForPreview(url, process) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (process.exitCode !== null) throw new Error('Zensical preview exited before startup.');
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The preview socket is not ready yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for the Zensical preview.');
}

// Serve Zensical behind Vite so the browser application and guides share an origin.
export function docsSite() {
  let docsProcess;
  return {
    name: 'polycolab-docs',
    apply: 'serve',
    async configureServer(server) {
      await syncBrandTokens();
      server.watcher.add(brandTokensSource);
      server.watcher.on('change', async (path) => {
        if (path === brandTokensSource) await syncBrandTokens();
      });
      const port = await availablePort();
      docsProcess = spawn(
        'uv',
        [
          'run',
          '--project',
          'docs-site',
          'zensical',
          'serve',
          '--config-file',
          'docs-site/mkdocs.yml',
          '--dev-addr',
          `127.0.0.1:${port}`,
        ],
        { cwd: repositoryRoot, stdio: ['ignore', 'pipe', 'pipe'] },
      );
      docsProcess.stdout.on('data', (chunk) => server.config.logger.info(String(chunk).trim()));
      docsProcess.stderr.on('data', (chunk) => server.config.logger.info(String(chunk).trim()));
      await waitForPreview(`http://127.0.0.1:${port}/`, docsProcess);

      server.config.server.proxy ??= {};
      server.config.server.proxy['^/docs(?:$|[/?])'] = {
        target: `http://127.0.0.1:${port}`,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/docs(?=\/|$)/, '') || '/',
      };

      server.httpServer?.once('close', () => {
        docsProcess?.kill('SIGTERM');
      });
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url, 'http://localhost');
        const target = {
          '/guide': '/docs/getting-started/',
          '/connect': '/docs/setup/external-agent/',
        }[url.pathname];
        if (!target) return next();
        response.writeHead(307, { Location: target + url.search });
        response.end();
      });
    },
  };
}
