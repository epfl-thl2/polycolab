import { getContext, setContext } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

export class ChatDraft {
  message = $state('');
  publicTask = $state('');
  startingSessionId = $state('');
  startRequest: { key: string; body: string } | undefined;
  request: { key: string; body: string } | undefined;
  get dirty() {
    return Boolean(this.message || this.publicTask);
  }
}

export function chatDraftKey(projectId: string, href: string) {
  const url = new URL(href, 'http://project.local');
  const sessionId = url.pathname.split('/')[4];
  return sessionId && sessionId !== 'new'
    ? `${projectId}:session:${sessionId}`
    : `${projectId}:new:${url.searchParams.get('draft') || 'default'}:${url.searchParams.get('worktree') || 'main'}`;
}

export class ChatDrafts {
  private entries = new SvelteMap<string, ChatDraft>();
  get(key: string) {
    let draft = this.entries.get(key);
    if (!draft) {
      draft = new ChatDraft();
      this.entries.set(key, draft);
    }
    return draft;
  }
  isDirty(key: string) {
    return this.entries.get(key)?.dirty ?? false;
  }
  discard(key: string) {
    const draft = this.entries.get(key);
    if (!draft) return;
    draft.message = '';
    draft.publicTask = '';
    draft.startingSessionId = '';
    draft.startRequest = undefined;
    draft.request = undefined;
  }
  delete(key: string) {
    this.entries.delete(key);
  }
  clear() {
    this.entries.clear();
  }
}

const key = Symbol('project-chat-drafts');
export function provideChatDrafts() {
  return setContext(key, new ChatDrafts());
}
export function chatDrafts() {
  return getContext<ChatDrafts | undefined>(key);
}
