import * as Y from 'yjs';
import {
  createLinearApi,
  type LinearState,
  type LinearOperation,
  type LinearDocument,
  type LinearCommand,
} from './linear-api';
import { bytesToBase64 } from './repository-api';
const decode = (text: string) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
const REMOTE = Symbol('committed update');
type OpenDocument = { doc: Y.Doc; undo: Y.UndoManager; sequence: number; value: LinearDocument };
type Pending = { request_id: string; body: { epoch: number; commands: LinearCommand[] } };
type FileDelta = {
  id: string;
  path: string;
  deleted: boolean;
  binary: boolean;
  executable: boolean;
  update?: string;
  content_base64?: string;
};

/** Per-project in-memory editing session. Saved always means a durable server receipt. */
export class LinearSession {
  readonly api;
  state?: LinearState;
  documents = new Map<string, OpenDocument>();
  pending = new Map<string, Pending>();
  recovery = new Map<string, string>();
  connected = false;
  error = '';
  activity = '';
  peers: { connection_id: string; user_id: string; label: string; file_id: string | null }[] = [];
  private activeFile: string | null = null;
  private socket?: WebSocket;
  private cursor = 0;
  private acknowledged = 0;
  private stopped = false;
  private reconnect?: ReturnType<typeof setTimeout>;
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private updates = new Map<string, Uint8Array[]>();
  private generation = 0;
  private opening = new Map<string, Promise<OpenDocument>>();
  private offline = () => {
    this.connected = false;
    clearTimeout(this.reconnect);
    this.socket?.close();
    this.changed();
  };
  private online = () => {
    void this.connect();
  };

  constructor(
    readonly projectId: string,
    private token: () => Promise<string | undefined | null>,
    private changed: () => void,
  ) {
    this.api = createLinearApi({ getAccessToken: token });
  }

  get saving() {
    return this.pending.size > 0 || this.updates.size > 0;
  }
  get writable() {
    return this.connected && Boolean(this.state?.writable) && !this.error;
  }

  async start() {
    window.addEventListener('offline', this.offline);
    window.addEventListener('online', this.online);
    this.state = await this.api.state(this.projectId);
    this.cursor = this.state.sequence;
    this.changed();
    await this.connect();
  }

  private async connect() {
    if (
      this.stopped ||
      !navigator.onLine ||
      this.socket?.readyState === WebSocket.OPEN ||
      this.socket?.readyState === WebSocket.CONNECTING
    )
      return;
    clearTimeout(this.reconnect);
    const token = await this.token();
    if (
      this.stopped ||
      !navigator.onLine ||
      this.socket?.readyState === WebSocket.OPEN ||
      this.socket?.readyState === WebSocket.CONNECTING
    )
      return;
    const url = new URL(
      `/api/v1/projects/${this.projectId}/linear/events`,
      import.meta.env.VITE_API_BASE_URL || location.origin,
    );
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket || this.stopped) return;
      socket.send(
        JSON.stringify({
          version: 1,
          after: this.cursor,
          authorization: token ? `Bearer ${token}` : undefined,
        }),
      );
      // The server validates access before replying to this ping.
      socket.send(JSON.stringify({ kind: 'ping' }));
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket || this.stopped || !navigator.onLine) return;
      const message = JSON.parse(event.data);
      if (message.kind === 'presence') {
        this.peers = message.peers;
      } else if (message.kind === 'pong') {
        this.connected = true;
        socket.send(JSON.stringify({ kind: 'presence', file_id: this.activeFile }));
        for (const value of this.pending.values()) this.send(value);
      } else if (message.kind === 'operation') {
        this.apply({ ...message, kind: message.operation_kind });
        this.cursor = message.sequence;
      } else if (message.kind === 'ack') {
        this.pending.delete(message.request_id);
        this.acknowledged = Math.max(this.acknowledged, message.sequence);
        // The ordered operation stream, not acknowledgements, advances the cursor.
      } else if (message.kind === 'rejected') {
        this.preserve();
        this.error = `Changes need recovery: ${message.error}`;
        this.pending.clear();
      }
      this.changed();
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      this.connected = false;
      if (event.code === 1008) {
        this.preserve();
        this.error = 'Access or workspace state changed. Copy your pending text before reopening.';
      } else if (!this.stopped && navigator.onLine) {
        this.reconnect = setTimeout(() => void this.connect(), 1000);
      }
      this.changed();
    };
  }

  private apply(operation: LinearOperation) {
    if (!this.state) return;
    if (operation.epoch !== this.state.epoch) {
      this.preserve();
      this.error = 'The project was restored. Copy any pending text, then reopen the workspace.';
      this.connected = false;
      this.stopped = true;
      this.socket?.close();
      return;
    }
    const newer = operation.sequence > this.state.sequence;
    const files = new Map(this.state.files.map((file) => [file.id, file]));
    for (const delta of operation.payload.files as FileDelta[]) {
      if (newer && delta.deleted) files.delete(delta.id);
      else if (newer)
        files.set(delta.id, {
          id: delta.id,
          path: delta.path,
          binary: delta.binary,
          executable: delta.executable,
          size: files.get(delta.id)?.size ?? 0,
        });
      const open = this.documents.get(delta.id);
      if (!open || operation.sequence <= open.sequence) continue;
      if (delta.deleted) {
        if (
          this.updates.has(delta.id) ||
          [...this.pending.values()].some((p) =>
            p.body.commands.some((c) => c.file_id === delta.id),
          )
        ) {
          this.recovery.set(open.value.path, open.doc.getText('content').toString());
          this.error = 'An edited file was deleted. Copy its pending text from recovery.';
        }
        open.value.deleted = true;
      } else {
        if (delta.update) Y.applyUpdate(open.doc, decode(delta.update), REMOTE);
        open.value.path = delta.path;
        open.value.executable = delta.executable;
        if (delta.content_base64 !== undefined) open.value.content_base64 = delta.content_base64;
      }
      open.sequence = operation.sequence;
    }
    this.state = {
      ...this.state,
      sequence: Math.max(this.state.sequence, operation.sequence),
      files: [...files.values()],
    };
    this.activity = operation.kind === 'agent' ? 'AI changes applied' : '';
  }

  focus(fileId: string | null) {
    if (this.activeFile === fileId) return;
    this.activeFile = fileId;
    if (this.socket?.readyState === WebSocket.OPEN && this.connected)
      this.socket.send(JSON.stringify({ kind: 'presence', file_id: fileId }));
  }

  async open(fileId: string) {
    const pending = this.opening.get(fileId);
    if (pending) return pending;
    const existing = this.documents.get(fileId);
    if (existing) return existing;
    const request = this.loadDocument(fileId);
    this.opening.set(fileId, request);
    try {
      return await request;
    } finally {
      this.opening.delete(fileId);
    }
  }

  private async loadDocument(fileId: string) {
    const version = this.generation;
    const value = await this.api.file(this.projectId, fileId);
    if (version !== this.generation || value.epoch !== this.state?.epoch)
      throw new Error('Workspace changed');
    const doc = new Y.Doc();
    if (value.document) Y.applyUpdate(doc, decode(value.document), REMOTE);
    const undo = new Y.UndoManager(doc.getText('content'), {
      trackedOrigins: new Set(['plain-editor']),
    });
    const opened = { doc, undo, sequence: value.sequence, value };
    this.documents.set(fileId, opened);
    doc.on('update', (update: Uint8Array, origin: unknown) => {
      if (origin === REMOTE) return;
      this.updates.set(fileId, [...(this.updates.get(fileId) ?? []), update]);
      if (!this.timers.has(fileId))
        this.timers.set(
          fileId,
          setTimeout(() => this.flushFile(fileId), 100),
        );
      this.changed();
    });
    await this.catchUp(value.sequence);
    return opened;
  }

  async catchUp(after = this.cursor, through = Infinity) {
    while (after < through) {
      const operations = await this.api.history(this.projectId, after);
      for (const operation of operations) this.apply(operation);
      if (!operations.length || operations.length < 100) break;
      after = operations.at(-1)!.sequence;
    }
  }

  private send(value: Pending) {
    if (this.socket?.readyState === WebSocket.OPEN && this.connected && !this.error)
      this.socket.send(JSON.stringify({ version: 1, kind: 'update', ...value }));
  }

  private flushFile(id: string) {
    const timer = this.timers.get(id);
    if (timer) clearTimeout(timer);
    this.timers.delete(id);
    const updates = this.updates.get(id);
    if (!updates?.length || !this.state) return;
    this.updates.delete(id);
    const value: Pending = {
      request_id: crypto.randomUUID(),
      body: {
        epoch: this.state.epoch,
        commands: [{ kind: 'update', file_id: id, update: bytesToBase64(Y.mergeUpdates(updates)) }],
      },
    };
    this.pending.set(value.request_id, value);
    this.send(value);
    this.changed();
  }

  async flush() {
    for (const id of this.updates.keys()) this.flushFile(id);
    const deadline = Date.now() + 15_000;
    while (this.pending.size || this.cursor < this.acknowledged) {
      if (!this.writable || Date.now() > deadline)
        throw new Error('Wait for your edits to be saved.');
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
  }

  async command(commands: LinearCommand[]) {
    await this.flush();
    if (!this.state || !this.writable) throw new Error('Workspace is not writable.');
    const accepted = await this.api.change(this.projectId, {
      epoch: this.state.epoch,
      expected_sequence: this.state.sequence,
      commands,
    });
    await this.catchUp(this.state.sequence, accepted.sequence);
    this.changed();
  }

  private preserve() {
    if (!this.saving) return;
    for (const value of this.documents.values())
      this.recovery.set(value.value.path, value.doc.getText('content').toString());
  }

  destroy() {
    this.stopped = true;
    window.removeEventListener('offline', this.offline);
    window.removeEventListener('online', this.online);
    this.generation++;
    clearTimeout(this.reconnect);
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.socket?.close();
    for (const entry of this.documents.values()) {
      entry.undo.destroy();
      entry.doc.destroy();
    }
  }
}
