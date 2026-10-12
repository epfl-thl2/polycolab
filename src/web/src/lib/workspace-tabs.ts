export type WorkspaceTab = {
  id: string;
  kind: 'chat' | 'file' | 'object' | 'diff' | 'page';
  label: string;
  href: string;
  dirty?: boolean;
  preview?: boolean;
};

export function isWorkspaceLayoutPage(href: string): boolean {
  const segments = new URL(href, 'http://workspace.local').pathname.split('/');
  return (
    !segments[4] &&
    [
      'overview',
      'research',
      'map',
      'activity',
      'settings',
      'agent-connect',
      'records',
      'references',
    ].includes(segments[3] || 'overview')
  );
}

export function workspaceRouteTab(projectId: string, href: string): WorkspaceTab | undefined {
  let url: URL;
  try {
    url = new URL(href, 'http://workspace.local');
  } catch {
    return;
  }
  if (url.origin !== 'http://workspace.local') return;
  const segments = url.pathname.split('/');
  if (!['workspaces', 'projects'].includes(segments[1]) || segments[2] !== projectId) return;
  const section = segments[3] || 'overview';
  const entity = segments[4];
  if (section === 'sessions' && !entity && url.searchParams.get('view') === 'empty') return;
  if (segments.length > 5) return;
  if (entity && !['objects', 'sessions', 'records', 'proposals', 'verification'].includes(section))
    return;
  if (section === 'objects' && !entity) return;
  const labels: Record<string, string> = {
    overview: 'Overview',
    research: 'Research objects',
    map: 'Map',
    activity: 'Activity',
    files: 'Files',
    sessions: 'All sessions',
    settings: 'Settings',
    'agent-connect': 'Agent connect',
    records: 'Research record',
    references: 'References',
    proposals: 'Proposal',
    verification: 'Verification',
  };
  const kind =
    section === 'objects' ? 'object' : section === 'sessions' && entity ? 'chat' : 'page';
  const label =
    kind === 'object'
      ? 'Research object'
      : kind === 'chat'
        ? entity === 'new'
          ? 'New chat'
          : 'Chat'
        : labels[section];
  if (!label) return;
  const draft = section === 'sessions' && entity === 'new' ? url.searchParams.get('draft') : null;
  return {
    id: `${section}:${entity || ''}${draft ? `:${draft}` : ''}`,
    kind,
    label,
    href: url.pathname + url.search,
  };
}

export function restoreWorkspaceTabs(projectId: string, raw: string | null): WorkspaceTab[] {
  try {
    const value: unknown = JSON.parse(raw || '[]');
    if (!Array.isArray(value)) return [];
    const seen = new Set<string>();
    return value.slice(0, 30).flatMap((item) => {
      if (!item || typeof item.href !== 'string') return [];
      const tab = workspaceRouteTab(projectId, item.href);
      if (!tab || tab.id === 'files:' || isWorkspaceLayoutPage(tab.href) || seen.has(tab.id))
        return [];
      seen.add(tab.id);
      return [tab];
    });
  } catch {
    return [];
  }
}
