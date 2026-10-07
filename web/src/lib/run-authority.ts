import type { components } from '@polycolab/api-client';

export type RunAuthority = components['schemas']['RunObjectVersionAuthorityRequest'];
export type TurnDraft = {
  destination: 'REVIEW' | 'WORKSPACE' | 'PUBLIC';
  privateMessage: string;
  publicTask: string;
  privateRevisions: string[];
  privateArtifacts: string[];
  publicRevisions: string[];
  publicTargets: string[];
  operations: NonNullable<RunAuthority['allowed_operations']>;
  editableObjects: string[];
  maxMutations: number;
  maxContentBytes: number;
};

export function prepareTurn(draft: TurnDraft) {
  const isPublic = draft.destination === 'PUBLIC';
  const artifactIds = [...new Set(draft.privateArtifacts)];
  if (isPublic && (!draft.publicTask.trim() || !draft.publicTargets.length))
    throw new Error('Select a public target and declare a separate public task.');
  if (!isPublic && artifactIds.length > 32)
    throw new Error('Select at most 32 exact committed artifacts for one private turn.');
  const authority: RunAuthority | undefined =
    draft.destination === 'REVIEW'
      ? undefined
      : {
          version: 1,
          destination: draft.destination,
          public_target_object_version_ids: isPublic ? [...new Set(draft.publicTargets)] : [],
          allowed_operations: [...draft.operations],
          editable_object_ids: draft.operations.includes('REVISE_RECORD')
            ? [...draft.editableObjects]
            : [],
          max_mutations: draft.maxMutations,
          max_content_bytes: draft.maxContentBytes,
          public_task_md: isPublic ? draft.publicTask.trim() : null,
        };
  return {
    // Never serialize the private draft or private selections into a public turn.
    content_md: isPublic ? draft.publicTask.trim() : draft.privateMessage.trim(),
    context_object_version_ids: [
      ...new Set(
        isPublic
          ? [...draft.publicRevisions, ...draft.publicTargets]
          : [...draft.privateRevisions, ...draft.publicRevisions],
      ),
    ],
    ...(!isPublic && artifactIds.length ? { context_artifact_ids: artifactIds } : {}),
    ...(authority ? { requested_authority: authority } : {}),
  };
}
