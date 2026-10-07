import { describe, expect, it } from 'vitest';
import { prepareTurn, type TurnDraft } from '../../../web/src/lib/run-authority';

const draft: TurnDraft = {
  destination: 'PUBLIC',
  privateMessage: 'PRIVATE CONVERSATION',
  publicTask: 'Explore the public lemma',
  privateRevisions: ['private-revision'],
  privateArtifacts: ['private-artifact', 'private-artifact'],
  publicRevisions: ['public-input'],
  publicTargets: ['public-target'],
  operations: ['CREATE_RECORD'],
  editableObjects: ['not-authorized-for-edit'],
  maxMutations: 3,
  maxContentBytes: 4096,
};

describe('explicit run authority', () => {
  it('excludes private drafts and revisions from public turn payloads', () => {
    const body = prepareTurn(draft);
    expect(body.content_md).toBe(draft.publicTask);
    expect(body.context_object_version_ids).toEqual(['public-input', 'public-target']);
    expect(body.requested_authority).toMatchObject({
      destination: 'PUBLIC',
      public_task_md: draft.publicTask,
      public_target_object_version_ids: ['public-target'],
      editable_object_ids: [],
      allowed_operations: ['CREATE_RECORD'],
      max_mutations: 3,
      max_content_bytes: 4096,
    });
    expect(JSON.stringify(body)).not.toContain('PRIVATE CONVERSATION');
    expect(JSON.stringify(body)).not.toContain('private-revision');
    expect(JSON.stringify(body)).not.toContain('private-artifact');
  });
  it('requires a separate public task and explicit targets', () => {
    expect(() => prepareTurn({ ...draft, publicTask: ' ' })).toThrow('separate public task');
    expect(() => prepareTurn({ ...draft, publicTargets: [] })).toThrow('public target');
  });
  it('retains reviewed-proposal behavior without requesting direct authority', () => {
    const body = prepareTurn({ ...draft, destination: 'REVIEW' });
    expect(body.requested_authority).toBeUndefined();
    expect(body.content_md).toBe(draft.privateMessage);
    expect(body.context_object_version_ids).toEqual(['private-revision', 'public-input']);
    expect(body.context_artifact_ids).toEqual(['private-artifact']);
  });
  it('grants workspace edits only for explicitly selected operations and objects', () => {
    const body = prepareTurn({
      ...draft,
      destination: 'WORKSPACE',
      operations: ['REVISE_RECORD'],
      editableObjects: ['editable-record'],
    });
    expect(body.requested_authority).toMatchObject({
      destination: 'WORKSPACE',
      public_task_md: null,
      public_target_object_version_ids: [],
      allowed_operations: ['REVISE_RECORD'],
      editable_object_ids: ['editable-record'],
    });
  });
  it('bounds explicit private artifact context', () => {
    expect(() =>
      prepareTurn({
        ...draft,
        destination: 'REVIEW',
        privateArtifacts: Array.from({ length: 33 }, (_, index) => `artifact-${index}`),
      }),
    ).toThrow('at most 32 exact committed artifacts');
  });
});
