import { getContext } from 'svelte';
import type { QueryClient } from '@tanstack/svelte-query';
import type { ProjectsApi } from '../lib/projects-api';
import type { AgentSessionsApi } from '../lib/agent-sessions-api';
import type { Auth } from './auth.svelte';
import type { createArtifactApi } from '../lib/artifact-api';
import type { createExternalAgentApi } from '../lib/external-agent-api';
export type ProjectContext = {
  defaultFiles?: boolean;
  linear?: import('../lib/linear-session').LinearSession;
  documentBuilds?: ReturnType<typeof import('../lib/document-builds-api').createDocumentBuildsApi>;
  tasks?: ReturnType<typeof import('../lib/project-tasks-api').createProjectTasksApi>;
  repository?: ReturnType<typeof import('../lib/repository-api').createRepositoryApi>;
  capabilities?: import('./capabilities.svelte').Capabilities;
  artifacts: ReturnType<typeof createArtifactApi>;
  externalAgents: ReturnType<typeof createExternalAgentApi>;
  auth: Auth;
  api: ProjectsApi;
  agents: AgentSessionsApi;
  query: QueryClient;
};
export const contextKey = Symbol('project');
export const projectContext = () => getContext<ProjectContext>(contextKey);
export const explain = (error: unknown) => {
  const status = (error as { status?: number })?.status;
  const code = (error as { code?: string })?.code;
  if (code === 'file_changed')
    return 'This file changed since you opened it. Your edits are retained. Copy them before reloading the current file.';
  if (code === 'file_exists' || code === 'file_path_conflict')
    return 'That path is already in use. Choose another file path.';
  if (code === 'latex_worker_unavailable')
    return 'The LaTeX compiler is unavailable. Your saved files are retained.';
  if (code === 'latex_worktree_busy')
    return 'A build is already active or stopping in this worktree. Wait for it to finish.';
  if (code === 'latex_stale_revision')
    return 'The saved files changed before compilation. Refresh and compile again.';
  if (code === 'latex_storage_full') return 'This project has reached its build storage limit.';
  if (code === 'latex_main_file_required') return 'Select a saved .tex file as the main document.';
  if (code === 'latex_queue_full')
    return 'This project has too many pending builds. Wait for a build to finish.';
  if (code === 'task_storage_disabled')
    return 'Working-copy storage is unavailable. Try again after it is enabled.';
  if (code === 'task_archived')
    return 'This task is archived. Restore it before making changes or starting an agent.';
  if (code === 'task_active')
    return 'This task has active or queued agent work. Wait for it to finish before changing its files or archiving it.';
  if (code === 'task_retry_conflict')
    return 'This task was already created with a different name. Refresh the task list before retrying.';
  if (code === 'project_task_not_found')
    return 'This task is unavailable or your project access changed.';
  if (code === 'repository_stale_save' || code === 'repository_stale_merge')
    return 'Someone saved newer changes. Compare the latest version before saving again.';
  if (code === 'repository_session_active')
    return 'This agent session has an active run. Wait for it to finish before editing or merging its branch.';
  if (code === 'repository_quota_exceeded' || code === 'repository_transfer_limit')
    return 'These files exceed the project storage or transfer limit. Store large outputs as artifacts.';
  if (code === 'repository_busy') return 'Another save is in progress. Please retry.';
  if (code === 'artifact_size_limit')
    return 'This file exceeds the configured upload limit. Choose a smaller file.';
  if (code === 'artifact_digest_mismatch' || code === 'artifact_length_mismatch')
    return 'The uploaded bytes did not match their declared identity. Keep the file and upload it again.';
  if (code === 'artifact_upload_timeout')
    return 'The upload timed out before verification. Keep the file and retry.';
  if (code === 'artifact_storage_unavailable')
    return 'Artifact storage is temporarily unavailable. Keep your file and retry.';
  if (code === 'credential_unavailable')
    return 'The secure key service is unavailable. Your entered key remains only in this form; retry when the service recovers.';
  if (code === 'provider_rejected')
    return 'The provider rejected validation. Check the endpoint, model, and replacement key, then retry.';
  if (code === 'provider_timeout' || code === 'provider_unavailable')
    return 'The provider could not be reached safely. Your settings are retained; retry later.';
  if (status === 403 || status === 404)
    return 'This resource is unavailable or your access changed. Return to your projects or retry.';
  if (status === 429) return 'The request limit has been reached. Please retry later.';
  if (status === 409)
    return code === 'conflict'
      ? 'The saved state or access changed. Refresh and retry.'
      : 'This resource changed while you were editing. Your draft is retained; compare it with the current version.';
  return error instanceof Error
    ? `Could not complete the request: ${error.message}. Please retry.`
    : 'Could not complete the request. Please retry.';
};
