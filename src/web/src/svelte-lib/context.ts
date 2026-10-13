import { getContext } from 'svelte';
import type { QueryClient } from '@tanstack/svelte-query';
import type { ResearchApi } from '../lib/research-api';
import type { AgentSessionsApi } from '../lib/agent-sessions-api';
import type { ProposalApi } from '../lib/proposals-api';
import type { Auth } from './auth.svelte';
import type { createCatalogueApi } from '../lib/catalogue-api';
import type { createRecordsApi } from '../lib/records-api';
import type { createCommunityApi } from '../lib/community-api';
import type { createResearchStructureApi } from '../lib/research-structure-api';
import type { createPublicationApi } from '../lib/publication-api';
import type { createArtifactApi } from '../lib/artifact-api';
import type { createVerificationApi } from '../lib/verification-api';
import type { SourceRevisionDraft } from '../lib/verification-view';
import type { createExternalAgentApi } from '../lib/external-agent-api';
export type Draft = {
  statementLabel?:
    'CLAIM' | 'CONJECTURE' | 'LEMMA' | 'PROPOSITION' | 'THEOREM' | 'COROLLARY' | null;
  originalStatementLabel?: Draft['statementLabel'];
  proofDirection?: 'SUPPORTS' | 'REFUTES';
  originalProofDirection?: Draft['proofDirection'];
  base: string;
  title: string;
  content: string;
  originalTitle: string;
  originalContent: string;
};
export type ProjectContext = {
  tasks?: ReturnType<typeof import('../lib/project-tasks-api').createProjectTasksApi>;
  repository?: ReturnType<typeof import('../lib/repository-api').createRepositoryApi>;
  capabilities?: import('./capabilities.svelte').Capabilities;
  history: ReturnType<typeof import('../lib/history-api').createHistoryApi>;
  catalogue: ReturnType<typeof createCatalogueApi>;
  records: ReturnType<typeof createRecordsApi>;
  community: ReturnType<typeof createCommunityApi>;
  researchStructure: ReturnType<typeof createResearchStructureApi>;
  publication: ReturnType<typeof createPublicationApi>;
  artifacts: ReturnType<typeof createArtifactApi>;
  verification: ReturnType<typeof createVerificationApi>;
  externalAgents: ReturnType<typeof createExternalAgentApi>;
  auth: Auth;
  api: ResearchApi;
  agents: AgentSessionsApi;
  proposals: ProposalApi;
  query: QueryClient;
  drafts: Map<string, Draft>;
  sourceDrafts: Map<string, SourceRevisionDraft>;
};
export const contextKey = Symbol('project');
export const projectContext = () => getContext<ProjectContext>(contextKey);
export const explain = (error: unknown) => {
  const status = (error as { status?: number })?.status;
  const code = (error as { code?: string })?.code;
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
  if (code === 'verification_environment_unavailable')
    return 'That curated environment is no longer available. Reload the environment list and choose an available exact version.';
  if (code === 'verification_limits_exceeded')
    return 'The requested limits exceed the selected environment ceilings. Review and lower the finite limits before retrying.';
  if (code === 'verification_inputs_exceed_disk')
    return 'The exact inputs exceed the requested disk limit. Increase that finite limit within the environment ceiling or select fewer inputs.';
  if (code === 'verification_source_kind_mismatch')
    return 'The saved source kind does not match the selected verification purpose. Choose an exact Lean formalization or Python computation revision.';
  if (code === 'credential_unavailable')
    return 'The secure key service is unavailable. Your entered key remains only in this form; retry when the service recovers.';
  if (code === 'provider_rejected')
    return 'The provider rejected validation. Check the endpoint, model, and replacement key, then retry.';
  if (code === 'provider_timeout' || code === 'provider_unavailable')
    return 'The provider could not be reached safely. Your settings are retained; retry later.';
  if (status === 403 || status === 404)
    return 'This research is unavailable or your access changed. Return to your projects or retry.';
  if (status === 429)
    return 'Verification admission capacity is exhausted. Your saved source and submission choices are retained; retry after capacity is released.';
  if (status === 409)
    return code === 'conflict'
      ? 'The saved state, exact dependency set, or authority changed. Review the current revisions and retry.'
      : 'This record changed while you were editing. Your draft is retained; compare with the latest revision.';
  return error instanceof Error
    ? `Could not complete the request: ${error.message}. Please retry.`
    : 'Could not complete the request. Please retry.';
};
