import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { prepare, type DocumentChange } from './engine.ts';

const token = process.env.COLLABORATION_TOKEN;
if (!token || token.length < 32)
  throw new Error('COLLABORATION_TOKEN must contain at least 32 characters');
const secret = Buffer.from(`Bearer ${token}`);
const presence = new Map<string, Map<string, { expires: number; value: unknown }>>();
const queues = new Map<string, Promise<unknown>>();
const server = createServer(async (request, response) => {
  response.setHeader('Content-Type', 'application/json');
  response.setHeader('Cache-Control', 'no-store');
  if (request.url === '/health/live' && request.method === 'GET') {
    response.end('{"ok":true}');
    return;
  }
  const supplied = Buffer.from(request.headers.authorization ?? '');
  if (supplied.length !== secret.length || !timingSafeEqual(supplied, secret)) {
    response.writeHead(401).end('{"error":"unauthorized"}');
    return;
  }
  if (!['/prepare', '/presence'].includes(request.url ?? '') || request.method !== 'POST') {
    response.writeHead(404).end('{"error":"not_found"}');
    return;
  }
  try {
    let size = 0;
    const chunks: Buffer[] = [];
    for await (const chunk of request) {
      size += chunk.length;
      if (size > 64 * 1024 * 1024) throw new Error('request_too_large');
      chunks.push(chunk);
    }
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
      project_id: string;
      documents: DocumentChange[];
    };
    if (request.url === '/presence') {
      const value = body as unknown as {
        project_id: string;
        connection_id: string;
        user_id: string;
        label: string;
        file_id: string | null;
        remove?: boolean;
      };
      if (!/^[0-9a-f-]{36}$/.test(value.project_id) || !/^[0-9a-f-]{36}$/.test(value.connection_id))
        throw new Error('invalid_presence');
      const now = Date.now();
      for (const [project, peers] of presence) {
        for (const [id, peer] of peers) if (peer.expires < now) peers.delete(id);
        if (!peers.size) presence.delete(project);
      }
      const peers = presence.get(value.project_id) ?? new Map();
      if (value.remove) peers.delete(value.connection_id);
      else {
        if (peers.size >= 200 && !peers.has(value.connection_id)) throw new Error('presence_limit');
        peers.set(value.connection_id, {
          expires: now + 15_000,
          value: {
            connection_id: value.connection_id,
            user_id: value.user_id,
            label: value.label.slice(0, 200),
            file_id: value.file_id,
          },
        });
      }
      presence.set(value.project_id, peers);
      response.end(JSON.stringify({ peers: [...peers.values()].map((peer) => peer.value) }));
      return;
    }
    if (
      !/^[0-9a-f-]{36}$/.test(body.project_id) ||
      !Array.isArray(body.documents) ||
      body.documents.length > 256
    )
      throw new Error('invalid_request');
    const previous = queues.get(body.project_id) ?? Promise.resolve();
    const work = previous.catch(() => undefined).then(() => body.documents.map(prepare));
    queues.set(body.project_id, work);
    try {
      response.end(JSON.stringify({ documents: await work }));
    } finally {
      if (queues.get(body.project_id) === work) queues.delete(body.project_id);
    }
  } catch {
    response.writeHead(422).end('{"error":"invalid_collaboration_update"}');
  }
});
server.requestTimeout = 30_000;
server.listen(
  Number(process.env.COLLABORATION_PORT ?? 8002),
  process.env.COLLABORATION_HOST ?? '127.0.0.1',
);
for (const signal of ['SIGINT', 'SIGTERM'] as const) process.on(signal, () => server.close());
