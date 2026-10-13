import { profileGroups, type ProfileFilter } from './profile-view';
import { validHistoryDay } from './contribution-history';

export type NavigateQuery = (search: string) => void;
const choice = <T extends string>(value: string | null, values: readonly T[], fallback: T): T =>
  values.includes(value as T) ? (value as T) : fallback;
export function readActivity(search: string) {
  const params = new URLSearchParams(search);
  return {
    view: choice(params.get('view'), ['recent', 'projects'] as const, 'recent'),
    window: choice(params.get('window'), ['day', 'week', 'month'] as const, 'week'),
    actor: choice(params.get('actor'), ['all', 'human', 'agent'] as const, 'all'),
    kind: 'all' as const,
    examples: params.get('preview') === 'examples',
  };
}
export function activityQuery(state: ReturnType<typeof readActivity>) {
  const params = new URLSearchParams();
  if (state.view !== 'recent') params.set('view', state.view);
  if (state.window !== 'week') params.set('window', state.window);
  if (state.actor !== 'all') params.set('actor', state.actor);
  if (state.examples) params.set('preview', 'examples');
  return params.toString();
}
export function readPeople(search: string) {
  const params = new URLSearchParams(search);
  return {
    query: (params.get('q') ?? '').trim().slice(0, 200),
    profile: params.get('profile') || undefined,
    examples: params.get('preview') === 'examples',
  };
}
export function peopleQuery(state: ReturnType<typeof readPeople>) {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
  if (state.profile) params.set('profile', state.profile);
  if (state.examples) params.set('preview', 'examples');
  return params.toString();
}
export function readSearch(search: string) {
  const params = new URLSearchParams(search);
  return {
    query: (params.get('q') ?? '').trim(),
    type: choice(params.get('type'), ['all', 'research', 'projects'] as const, 'all'),
  };
}
export function readProfile(search: string) {
  const params = new URLSearchParams(search);
  const day = validHistoryDay(params.get('day'));
  const requestedYear = params.get('year') ?? '';
  const year =
    /^\d{4}$/.test(requestedYear) &&
    Number(requestedYear) >= 1970 &&
    Number(requestedYear) <= new Date().getUTCFullYear()
      ? Number(requestedYear)
      : undefined;
  return {
    query: (params.get('q') ?? '').trim().slice(0, 200),
    day,
    year: day ? Number(day.slice(0, 4)) : year,
    type: choice<ProfileFilter>(
      params.get('type'),
      ['all', ...profileGroups.map((group) => group.id)],
      'all',
    ),
  };
}
export function profileQuery(state: {
  query: string;
  type: ProfileFilter;
  day?: string;
  year?: number;
}) {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
  if (state.type !== 'all') params.set('type', state.type);
  if (state.year) params.set('year', String(state.year));
  if (state.day) params.set('day', state.day);
  return params.toString();
}
export function searchQuery(query: string, type: ReturnType<typeof readSearch>['type'] = 'all') {
  const params = new URLSearchParams();
  if (query.trim()) params.set('q', query.trim());
  if (type !== 'all') params.set('type', type);
  return params.toString();
}
export function canonicalUiLocation(path: string, search: string) {
  // Browser bookmark compatibility only; API callers must adopt the new contract.
  const renamed = path
    .replace(/^\/workspaces(?=\/|$)/, '/projects')
    .replace(/^\/demo\/workspaces(?=\/|$)/, '/demo/projects');
  if (renamed !== path) return renamed + search;
  if (path === '/activity/workspaces') return '/activity/projects' + search;
  if (path === '/settings/providers') return '/settings/model-providers' + search;
  if (path === '/settings/agent-keys') return '/settings/api-keys' + search;
  let query: string;
  if (path === '/' || path === '/search') {
    const state = readSearch(search);
    path = '/';
    query = searchQuery(state.query, state.type);
  } else if (['/activity', '/activity/recent', '/activity/projects'].includes(path)) {
    const state = readActivity(search);
    if (path === '/activity/projects') state.view = 'projects';
    if (path === '/activity/recent') state.view = 'recent';
    path = '/activity';
    query = activityQuery(state);
  } else if (path === '/people') query = peopleQuery(readPeople(search));
  else if (path === '/profile') query = profileQuery(readProfile(search));
  else return path + search;
  return path + (query ? `?${query}` : '');
}
