import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';

export type Project = components['schemas']['ProjectMemberRead'];
export type PublicProject = components['schemas']['PublicProjectRead'];
export type Role = components['schemas']['ProjectRole'];
export type Membership = components['schemas']['MembershipRead'];
export type MembershipInput =
  | { username: string; user_id?: never; role: Role }
  | { user_id: string; username?: never; role: Role };
export type Invitation = components['schemas']['InvitationRead'];
export type GatewayProfile = components['schemas']['GatewayProfileRead'];
export interface Page<T> {
  total?: number;
  items: T[];
  nextCursor?: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string = 'request_failed',
  ) {
    super(code);
  }
}

export interface ProjectsApi {
  listProjects(
    cursor?: string,
    query?: string,
    category?: 'active' | 'owned' | 'shared' | 'archived',
    sort?: 'updated' | 'name' | 'name_desc' | 'relevance',
  ): Promise<Page<Project>>;
  createProject(input: {
    workspace_mode?: 'default' | 'linear' | 'git';
    name: string;
    description?: string;
    visibility: components['schemas']['ProjectVisibility'];
  }): Promise<Project>;
  getProject(projectId: string): Promise<Project>;
  updateProject(
    projectId: string,
    input: {
      name?: string;
      description?: string;
      visibility?: components['schemas']['ProjectVisibility'];
      archived?: boolean;
    },
  ): Promise<Project>;
  deleteProject(projectId: string): Promise<void>;
  listMembers(projectId: string, cursor?: string): Promise<Page<Membership>>;
  addMember(projectId: string, input: MembershipInput): Promise<Membership>;
  updateMember(projectId: string, userId: string, role: Role): Promise<Membership>;
  removeMember(projectId: string, userId: string): Promise<void>;
  listInvitations(projectId: string, cursor?: string): Promise<Page<Invitation>>;
  createInvitation(projectId: string, input: { email: string; role: Role }): Promise<Invitation>;
  revokeInvitation(projectId: string, invitationId: string): Promise<void>;
  listGatewayProfiles(cursor?: string): Promise<Page<GatewayProfile>>;
  createGatewayProfile(input: {
    display_name: string;
    base_url: string;
    model_id: string;
    api_key: string;
  }): Promise<GatewayProfile>;
  rotateGatewayProfile(profileId: string, apiKey: string): Promise<GatewayProfile>;
  validateGatewayProfile(profileId: string): Promise<GatewayProfile>;
  deleteGatewayProfile(profileId: string): Promise<void>;
  getPublicProject(projectId: string): Promise<PublicProject>;
  listPublicProjects(
    query?: string,
    cursor?: string,
    sort?: 'updated' | 'name' | 'name_desc' | 'relevance',
  ): Promise<Page<PublicProject>>;
  currentUser(): Promise<components['schemas']['UserRead']>;
  chooseUsername(username: string): Promise<components['schemas']['UserRead']>;
}

type ErrorBody = { error?: { code?: string } };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok) return data as T;
  const code = (error as ErrorBody | undefined)?.error?.code ?? 'request_failed';
  throw new ApiError(response.status, code);
}

async function unwrapPage<T>(
  result: Promise<{
    data?: T[] | { items: T[]; next_cursor?: string | null; total?: number };
    error?: unknown;
    response: Response;
  }>,
): Promise<Page<T>> {
  const { data, error, response } = await result;
  if (data !== undefined) {
    return Array.isArray(data)
      ? { items: data, nextCursor: response.headers.get('X-Next-Cursor') ?? undefined }
      : { items: data.items, nextCursor: data.next_cursor ?? undefined, total: data.total };
  }
  const code = (error as ErrorBody | undefined)?.error?.code ?? 'request_failed';
  throw new ApiError(response.status, code);
}

/**
 * The only browser adapter for project and account resources. Authentication is
 * deliberately injected by the application shell; this UI never treats a
 * displayed role as authorization.
 */
export function createProjectsApi(
  options: {
    baseUrl?: string;
    signal?: AbortSignal;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
): ProjectsApi {
  const clientOptions = {
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '',
  };
  const memberClient = createWebApiClient(clientOptions);
  const publicClient = memberClient;
  memberClient.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (!token)
        return options.signal ? new Request(request, { signal: options.signal }) : undefined;
      const headers = new Headers(request.headers);
      headers.set('Authorization', `Bearer ${token}`);
      return new Request(request, {
        headers,
        ...(options.signal ? { signal: options.signal } : {}),
      });
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });
  const pageQuery = (cursor?: string) => ({ limit: 25, ...(cursor ? { cursor } : {}) });

  return {
    listProjects: (cursor, q, category, sort) =>
      unwrapMemberPage<Project>(
        memberClient.GET('/api/v1/projects', {
          params: {
            query: { limit: 20, cursor, q: q || undefined, category, sort, scope: 'member' },
          },
        }),
      ),
    createProject: (body) =>
      unwrap(
        memberClient.POST('/api/v1/projects', { body: { workspace_mode: 'default', ...body } }),
      ),
    getProject: (projectId) =>
      unwrapMember<Project>(
        memberClient.GET('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
        }),
      ),
    updateProject: (projectId, body) =>
      unwrap(
        memberClient.PATCH('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    deleteProject: (projectId) =>
      unwrap(
        memberClient.DELETE('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
        }),
      ),
    listMembers: (projectId, cursor) =>
      unwrapPage(
        memberClient.GET('/api/v1/projects/{project_id}/members', {
          params: { path: { project_id: projectId }, query: pageQuery(cursor) },
        }),
      ),
    addMember: (projectId, body) =>
      unwrap(
        memberClient.POST('/api/v1/projects/{project_id}/members', {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    updateMember: (projectId, userId, role) =>
      unwrap(
        memberClient.PATCH('/api/v1/projects/{project_id}/members/{member_user_id}', {
          params: { path: { project_id: projectId, member_user_id: userId } },
          body: { role },
        }),
      ),
    removeMember: (projectId, userId) =>
      unwrap(
        memberClient.DELETE('/api/v1/projects/{project_id}/members/{member_user_id}', {
          params: { path: { project_id: projectId, member_user_id: userId } },
        }),
      ),
    listInvitations: (projectId, cursor) =>
      unwrapPage(
        memberClient.GET('/api/v1/projects/{project_id}/invitations', {
          params: { path: { project_id: projectId }, query: pageQuery(cursor) },
        }),
      ),
    createInvitation: (projectId, body) =>
      unwrap(
        memberClient.POST('/api/v1/projects/{project_id}/invitations', {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    revokeInvitation: (projectId, invitationId) =>
      unwrap(
        memberClient.DELETE('/api/v1/projects/{project_id}/invitations/{invitation_id}', {
          params: { path: { project_id: projectId, invitation_id: invitationId } },
        }),
      ),
    listGatewayProfiles: (cursor) =>
      unwrapPage(
        memberClient.GET('/api/v1/gateway/profiles', {
          params: { query: pageQuery(cursor) },
        }),
      ),
    createGatewayProfile: (body) =>
      unwrap(
        memberClient.POST('/api/v1/gateway/profiles', { body: { ...body, wire_api: 'responses' } }),
      ),
    rotateGatewayProfile: (profileId, api_key) =>
      unwrap(
        memberClient.POST('/api/v1/gateway/profiles/{profile_id}/rotate', {
          params: { path: { profile_id: profileId } },
          body: { api_key },
        }),
      ),
    validateGatewayProfile: (profileId) =>
      unwrap(
        memberClient.POST('/api/v1/gateway/profiles/{profile_id}/validate', {
          params: { path: { profile_id: profileId } },
        }),
      ),
    deleteGatewayProfile: (profileId) =>
      unwrap(
        memberClient.DELETE('/api/v1/gateway/profiles/{profile_id}', {
          params: { path: { profile_id: profileId } },
        }),
      ),
    getPublicProject: (projectId) =>
      unwrap(
        publicClient.GET('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
        }),
      ),
    listPublicProjects: (q, cursor, sort) =>
      unwrapPage(
        publicClient.GET('/api/v1/projects', {
          params: { query: { limit: 20, q: q || undefined, cursor: cursor || undefined, sort } },
        }),
      ),
    currentUser: () => unwrap(memberClient.GET('/api/v1/users/me')),
    chooseUsername: (username) =>
      unwrap(memberClient.PUT('/api/v1/account/username', { body: { username } })),
  };
}

async function unwrapMember<T>(
  result: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<T> {
  return (await unwrap(result)) as T;
}

async function unwrapMemberPage<T>(
  result: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<Page<T>> {
  const data = (await unwrap(result)) as {
    items: T[];
    next_cursor?: string | null;
    total?: number;
  };
  return { items: data.items, nextCursor: data.next_cursor ?? undefined, total: data.total };
}
