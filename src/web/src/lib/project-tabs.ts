import { canonicalUiLocation } from './ui-location';
export type ProjectTab = {
  id: string;
  kind: 'chat' | 'file' | 'diff' | 'page';
  label: string;
  href: string;
  dirty?: boolean;
  preview?: boolean;
};

export function isProjectLayoutPage(href: string): boolean {
  const segments = new URL(href, 'http://project.local').pathname.split('/');
  return (
    !segments[4] && ['overview', 'settings', 'agent-connect'].includes(segments[3] || 'overview')
  );
}

export function projectRouteTab(projectId: string, href: string): ProjectTab | undefined {
  let url: URL;
  try {
    url = new URL(href, 'http://project.local');
  } catch {
    return;
  }
  if (url.origin !== 'http://project.local') return;
  const segments = url.pathname.split('/');
  if (!['workspaces', 'projects'].includes(segments[1]) || segments[2] !== projectId) return;
  const section = segments[3] || 'overview';
  const entity = segments[4];
  if (section === 'sessions' && !entity && url.searchParams.get('view') === 'empty') return;
  if (segments.length > 5) return;
  if (entity && section !== 'sessions') return;
  const labels: Record<string, string> = {
    overview: 'Overview',
    files: 'Files',
    sessions: 'All sessions',
    settings: 'Settings',
    'agent-connect': 'Agent connect',
  };
  const kind = section === 'sessions' && entity ? 'chat' : 'page';
  const label = kind === 'chat' ? (entity === 'new' ? 'New chat' : 'Chat') : labels[section];
  if (!label) return;
  const draft = section === 'sessions' && entity === 'new' ? url.searchParams.get('draft') : null;
  return {
    id: `${section}:${entity || ''}${draft ? `:${draft}` : ''}`,
    kind,
    label,
    href: canonicalUiLocation(url.pathname, url.search) + url.hash,
  };
}

export function restoreProjectTabs(projectId: string, raw: string | null): ProjectTab[] {
  try {
    const value: unknown = JSON.parse(raw || '[]');
    if (!Array.isArray(value)) return [];
    const seen = new Set<string>();
    return value.slice(0, 30).flatMap((item) => {
      if (!item || typeof item.href !== 'string') return [];
      const tab = projectRouteTab(projectId, item.href);
      if (!tab || tab.id === 'files:' || isProjectLayoutPage(tab.href) || seen.has(tab.id))
        return [];
      seen.add(tab.id);
      return [tab];
    });
  } catch {
    return [];
  }
}
