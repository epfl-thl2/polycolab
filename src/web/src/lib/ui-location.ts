export type NavigateQuery = (search: string) => void;
export function canonicalUiLocation(path: string, search: string) {
  const renamed = path.replace(/^\/workspaces(?=\/|$)/, '/projects');
  if (/^\/projects\/[^/]+\/chat\/?$/.test(renamed))
    return renamed.replace(/\/chat\/?$/, '/sessions') + search;
  if (path === '/settings/providers') return '/settings/model-providers' + search;
  if (path === '/settings/agent-keys') return '/settings/api-keys' + search;
  return renamed + search;
}
