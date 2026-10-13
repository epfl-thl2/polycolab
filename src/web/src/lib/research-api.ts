import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';

export type Project = components['schemas']['ProjectMemberRead'];
export type PublicProject = components['schemas']['PublicProjectRead'];
export type ResearchObject = components['schemas']['MemberVersionedObjectRead'];
export type PublicResearchObject = components['schemas']['PublicVersionedObjectRead'];
export type ObjectVersion = PublicResearchObject['current_object_version'];
export type Relation =
  | components['schemas']['UnidirectionalRelationshipRead']
  | components['schemas']['BidirectionalRelationshipRead'];
export type PublicRelation = Relation;
export type VersionSnapshot = components['schemas']['VersionedObjectCreate']['snapshot'];
export type VersionCreate = components['schemas']['ObjectVersionCreate'];
export type RelationshipCreate =
  | components['schemas']['UnidirectionalDeclarationCreate']
  | components['schemas']['BidirectionalDeclarationCreate'];
export type Comment = components['schemas']['CommentRead'];
export type PublicComment = components['schemas']['PublicCommentRead'];
export type Role = components['schemas']['ProjectRole'];
export type ObjectKind = components['schemas']['ObjectKind'];
export type RelationType = RelationshipCreate['relationship_type'];
export type Membership = components['schemas']['MembershipRead'];
export type MembershipInput =
  | { username: string; user_id?: never; role: Role }
  | { user_id: string; username?: never; role: Role };
export type Invitation = components['schemas']['InvitationRead'];
export type GatewayProfile = components['schemas']['GatewayProfileRead'];
export type NeighborhoodNode = {
  object_version_id: string;
  object_id: string;
  title: string;
};

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

export interface ResearchApi {
  listProjects(
    cursor?: string,
    query?: string,
    category?: 'active' | 'owned' | 'shared' | 'archived',
    sort?: 'updated' | 'name' | 'name_desc' | 'relevance',
  ): Promise<Page<Project>>;
  createProject(input: {
    workspace_mode?: 'linear' | 'git';
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
  listObjects(
    projectId: string,
    publicRead?: boolean,
    cursor?: string,
  ): Promise<Page<ResearchObject | PublicResearchObject>>;
  getObject(
    projectId: string,
    objectId: string,
    publicRead?: boolean,
  ): Promise<ResearchObject | PublicResearchObject>;
  listVersions(
    projectId: string,
    objectId: string,
    publicRead?: boolean,
    cursor?: string,
  ): Promise<Page<ObjectVersion>>;
  getVersion(objectVersionId: string): Promise<ObjectVersion>;
  listRelations(
    projectId: string,
    objectId: string,
    publicRead?: boolean,
    cursor?: string,
  ): Promise<Page<Relation | PublicRelation>>;
  neighborhood(
    projectId: string,
    objectId: string,
    revisionId?: string,
    publicRead?: boolean,
  ): Promise<{
    object_version_id: string;
    relationships: Relation[];
    nodes: NeighborhoodNode[];
  }>;
  listComments(objectId: string, cursor?: string): Promise<Page<Comment>>;
  listPublicComments(
    projectId: string,
    objectId: string,
    cursor?: string,
  ): Promise<Page<PublicComment>>;
  createObject(projectId: string, input: VersionSnapshot): Promise<ResearchObject>;
  createVersion(objectId: string, input: VersionCreate): Promise<ResearchObject>;
  createRelation(objectId: string, input: RelationshipCreate): Promise<Relation>;
  createComment(
    objectId: string,
    input: { object_version_id: string; body_md: string },
  ): Promise<Comment>;
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
 * The only browser adapter for canonical research data. Authentication is
 * deliberately injected by the application shell; this UI never treats a
 * displayed role as authorization.
 */
export function createResearchApi(
  options: {
    baseUrl?: string;
    signal?: AbortSignal;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
): ResearchApi {
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

  const retryKeys = new Map<string, string>();
  async function retryWrite<T>(
    operation: string,
    body: unknown,
    send: (key: string) => Promise<T>,
  ): Promise<T> {
    const fingerprint = JSON.stringify([operation, body]);
    const key = retryKeys.get(fingerprint) ?? crypto.randomUUID();
    retryKeys.set(fingerprint, key);
    const value = await send(key);
    retryKeys.delete(fingerprint);
    return value;
  }
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
      unwrap(memberClient.POST('/api/v1/projects', { body: { workspace_mode: 'git', ...body } })),
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
    listObjects: (projectId, publicRead, cursor) =>
      publicRead
        ? unwrapPage(
            publicClient.GET('/api/v1/projects/{project_id}/objects', {
              params: { path: { project_id: projectId }, query: pageQuery(cursor) },
            }),
          )
        : unwrapPage(
            memberClient.GET('/api/v1/projects/{project_id}/objects', {
              params: { path: { project_id: projectId }, query: pageQuery(cursor) },
            }),
          ),
    getObject: (projectId, objectId, publicRead) =>
      publicRead
        ? unwrap(
            publicClient.GET('/api/v1/objects/{object_id}', {
              params: { path: { object_id: objectId } },
            }),
          )
        : unwrap(
            memberClient.GET('/api/v1/objects/{object_id}', {
              params: { path: { object_id: objectId } },
            }),
          ),
    getVersion: (objectVersionId) =>
      unwrap(
        memberClient.GET('/api/v1/versions/{object_version_id}', {
          params: { path: { object_version_id: objectVersionId } },
        }),
      ),
    listVersions: (projectId, objectId, publicRead, cursor) =>
      publicRead
        ? unwrapPage(
            publicClient.GET('/api/v1/objects/{object_id}/versions', {
              params: {
                path: { object_id: objectId },
                query: pageQuery(cursor),
              },
            }),
          )
        : unwrapPage(
            memberClient.GET('/api/v1/objects/{object_id}/versions', {
              params: { path: { object_id: objectId }, query: pageQuery(cursor) },
            }),
          ),
    listRelations: (projectId, objectId, publicRead, cursor) =>
      publicRead
        ? unwrapPage(
            publicClient.GET('/api/v1/objects/{object_id}/relations', {
              params: {
                path: { object_id: objectId },
                query: pageQuery(cursor),
              },
            }),
          )
        : unwrapPage(
            memberClient.GET('/api/v1/objects/{object_id}/relations', {
              params: { path: { object_id: objectId }, query: pageQuery(cursor) },
            }),
          ),
    neighborhood: (projectId, objectId, revisionId, publicRead) =>
      publicRead
        ? Promise.reject(new ApiError(404, 'not_found'))
        : unwrap(
            memberClient.GET('/api/v1/objects/{object_id}/neighborhood', {
              params: {
                path: { object_id: objectId },
                query: revisionId ? { object_version_id: revisionId } : {},
              },
            }),
          ),
    listComments: (objectId, cursor) =>
      unwrapMemberPage<Comment>(
        memberClient.GET('/api/v1/objects/{object_id}/comments', {
          params: { path: { object_id: objectId }, query: pageQuery(cursor) },
        }),
      ),
    listPublicComments: (projectId, objectId, cursor) =>
      unwrapPage(
        publicClient.GET('/api/v1/objects/{object_id}/comments', {
          params: {
            path: { object_id: objectId },
            query: pageQuery(cursor),
          },
        }),
      ),
    createObject: (projectId, body) =>
      retryWrite(`object.create:${projectId}`, body, async (key) => {
        const receipt = await unwrap(
          memberClient.POST('/api/v1/objects', {
            params: { header: { 'Idempotency-Key': key } },
            body: {
              snapshot: body,
              destination: { kind: 'project', project_id: projectId },
            },
          }),
        );
        const id = receipt.outputs.find(
          (output) => output.entity_type === 'RESEARCH_OBJECT',
        )!.entity_id;
        return unwrapMember<ResearchObject>(
          memberClient.GET('/api/v1/objects/{object_id}', { params: { path: { object_id: id } } }),
        );
      }),
    createVersion: (objectId, body) =>
      retryWrite(`object.revise:${objectId}`, body, async (key) => {
        await unwrap(
          memberClient.POST('/api/v1/objects/{object_id}/versions', {
            params: { path: { object_id: objectId }, header: { 'Idempotency-Key': key } },
            body,
          }),
        );
        return unwrapMember<ResearchObject>(
          memberClient.GET('/api/v1/objects/{object_id}', {
            params: { path: { object_id: objectId } },
          }),
        );
      }),
    createRelation: (objectId, body) =>
      retryWrite(`relation:${objectId}`, body, async (key) => {
        const receipt = await unwrap(
          memberClient.POST('/api/v1/relations', {
            params: { header: { 'Idempotency-Key': key } },
            body,
          }),
        );
        const id = receipt.outputs[0]!.entity_id;
        let cursor: string | undefined;
        do {
          const page: Page<Relation> = await unwrapMemberPage<Relation>(
            memberClient.GET('/api/v1/objects/{object_id}/relations', {
              params: { path: { object_id: objectId }, query: pageQuery(cursor) },
            }),
          );
          const row = page.items.find((item) => item.id === id);
          if (row) return row;
          cursor = page.nextCursor;
        } while (cursor);
        throw new ApiError(404, 'not_found');
      }),
    createComment: (objectId, body) =>
      retryWrite(`comment:${objectId}`, body, async (key) => {
        const receipt = await unwrap(
          memberClient.POST('/api/v1/objects/{object_id}/comments', {
            params: { path: { object_id: objectId }, header: { 'Idempotency-Key': key } },
            body,
          }),
        );
        const id = receipt.outputs[0]!.entity_id;
        let cursor: string | undefined;
        do {
          const page: Page<Comment> = await unwrapMemberPage<Comment>(
            memberClient.GET('/api/v1/objects/{object_id}/comments', {
              params: { path: { object_id: objectId }, query: pageQuery(cursor) },
            }),
          );
          const row = page.items.find((item) => item.id === id);
          if (row) return row;
          cursor = page.nextCursor;
        } while (cursor);
        throw new ApiError(404, 'not_found');
      }),
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
