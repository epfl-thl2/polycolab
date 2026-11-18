import { getContext, setContext } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

export class ChatDraft {
  message = $state('');
  startingConversationId = $state('');
  startRequest: { key: string; body: string } | undefined;
  request: { key: string; body: string } | undefined;
  get dirty() {
    return Boolean(this.message);
  }
}

export function chatDraftKey(projectId: string, href: string) {
  const url = new URL(href, 'http://project.local');
  const conversationId = url.pathname.split('/')[4];
  return conversationId && conversationId !== 'new'
    ? `${projectId}:conversation:${conversationId}`
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
  newChatHref(
    projectId: string,
    tabs: { kind: string; href: string }[],
    worktreeId: string | null = null,
    singleComposer = false,
  ) {
    const existing = tabs.find((tab) => {
      const url = new URL(tab.href, 'http://project.local');
      if (
        tab.kind !== 'chat' ||
        url.pathname !== `/projects/${projectId}/conversations/new` ||
        url.searchParams.get('worktree') !== worktreeId
      )
        return false;
      const draft = this.entries.get(chatDraftKey(projectId, tab.href));
      return singleComposer || (!draft?.dirty && !draft?.startingConversationId);
    });
    return (
      existing?.href ??
      `/projects/${projectId}/conversations/new?draft=${crypto.randomUUID()}${worktreeId ? `&worktree=${encodeURIComponent(worktreeId)}` : ''}`
    );
  }
  isDirty(key: string) {
    return this.entries.get(key)?.dirty ?? false;
  }
  discard(key: string) {
    const draft = this.entries.get(key);
    if (!draft) return;
    draft.message = '';
    draft.startingConversationId = '';
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
