import { expect, it } from 'vitest';
import { claimVersion, structuralPin } from './version-fixtures';
import {
  mapAuthoredSummary,
  mapHumanNote,
  mapProofSketch,
  mapResearchAttempt,
} from '../../../web/src/lib/research-structure-mappers';

const base = {
  schema_version: 1,
  structural_relationships: [{ target_version_id: 'claim-r3', role: 'ATTACHMENT' }],
  object_id: 'sketch-object',
  object_version_id: 'sketch-r2',
  number: 2,
  base_revision_id: 'sketch-r1',
  kind: 'PROOF',
  title: 'Route',
  content_md: 'Proof',
  assumptions_md: 'None stated',
  statement_revision_ids: ['claim-r3'],
  reported_outcome: null,
  explanation_md: null,
  actor_kind: 'HUMAN',
  author_display_name: 'Ada',
  agent_display_name: null,
  created_at: '2026-09-07T00:00:00Z',
};

it('maps generated assurance without conflating withdrawal and correspondence', () => {
  const view = mapProofSketch(
    {
      id: 'sketch-r2',
      object_id: 'sketch-object',
      number: 2,
      kind: 'PROOF',
      previous_object_version_id: 'sketch-r1',
      schema_version: 1,
      change_summary: null,
      created_at: base.created_at,
      authorship: {
        actor_kind: 'HUMAN',
        author_display_name: 'Ada',
        author_user_id: null,
        agent_id: null,
        agent_display_name: null,
        contribution_id: null,
        sponsor_user_id: null,
      },
      content: {
        title: 'Route',
        content_md: 'Proof',
        assumptions_md: 'None stated',
        reported_outcome: null,
        explanation_md: null,
        reported_progress: 'COMPLETE',
      },
      structural_relationships: [
        {
          relationship_type: 'CONCLUSION' as const,
          target_object_version_id: 'claim-r3',
          position: null,
        },
        {
          relationship_type: 'PREMISE' as const,
          target_object_version_id: 'lemma-r1',
          position: 7,
        },
      ].map((pin, index) => ({
        ...pin,
        id: `pin-${index}`,
        binding: 'STRUCTURAL',
        direction: 'UNIDIRECTIONAL',
        source_object_version_id: 'sketch-r2',
        ownership_scope_id: null,
        description: null,
        evidence_role: null,
        created_at: base.created_at,
        authorship: {
          actor_kind: 'HUMAN',
          author_display_name: 'Ada',
          author_user_id: null,
          agent_id: null,
          agent_display_name: null,
          contribution_id: null,
          sponsor_user_id: null,
        },
      })),
    },
    {
      object_version_id: 'sketch-r2',
      endorsements: [
        {
          id: 'e1',
          object_version_id: 'sketch-r2',
          assessor_id: 'grace-user',
          active: false,
          rationale: 'Changed view',
          author_display_name: 'Grace',
          created_at: '2026-09-07T00:00:00Z',
        },
        {
          id: 'e2',
          object_version_id: 'sketch-r2',
          assessor_id: 'sofia-user',
          active: true,
          rationale: 'Still endorsed',
          author_display_name: 'Sofia',
          created_at: '2026-09-06T00:00:00Z',
        },
      ],
      correspondence: [
        {
          id: 'c1',
          object_version_id: 'sketch-r2',
          assessor_id: 'emmy-user',
          statement_object_version_id: 'claim-r3',
          status: 'MISMATCH',
          rationale: 'Different claim',
          author_display_name: 'Emmy',
          created_at: '2026-09-07T00:00:00Z',
        },
      ],
      next_cursor: null,
    },
    {
      object_version_id: 'sketch-r2',
      endorsements: [
        {
          id: 'e1',
          object_version_id: 'sketch-r2',
          assessor_id: 'grace-user',
          active: false,
          rationale: 'Changed view',
          author_display_name: 'Grace',
          created_at: '2026-09-07T00:00:00Z',
        },
      ],
      correspondence: [
        {
          id: 'c1',
          object_version_id: 'sketch-r2',
          assessor_id: 'emmy-user',
          statement_object_version_id: 'claim-r3',
          status: 'MISMATCH',
          rationale: 'Different claim',
          author_display_name: 'Emmy',
          created_at: '2026-09-07T00:00:00Z',
        },
      ],
    },
    (id) => ({ title: id === 'claim-r3' ? 'Claim' : 'Lemma', href: `/${id}` }),
    '/sketch-r2',
    'claim-r3',
  );
  expect(view).toMatchObject({
    sketchId: 'sketch-object',
    endorsement: 'DISAGREEMENT',
    correspondence: 'MISMATCH',
    reportedProgress: 'COMPLETE',
    historical: false,
  });
  expect(view?.currentEndorsements).toHaveLength(2);
  expect(view?.endorsementHistory).toHaveLength(1);
  expect(view?.premises[0]).toMatchObject({ revisionId: 'lemma-r1', title: 'Lemma' });
});

it('maps generated research attempts with exact evidence and result identities', () => {
  const view = mapResearchAttempt(
    {
      ...claimVersion(),
      object_id: 'attempt-object',
      id: 'attempt-r1',
      kind: 'ATTEMPT',
      legacy_unstructured: false,
      content: {
        ...claimVersion().content,
        title: 'Try induction',
        outcome: 'PARTIAL',
        findings_md: 'Need a lemma',
      },
      structural_relationships: [
        structuralPin('attempt-r1', 'claim-r3', 'TARGET'),
        {
          ...structuralPin('attempt-r1', 'lemma-r1', 'TARGET'),
          relationship_type: 'EVIDENCE',
          evidence_role: 'SUPPORTS',
          position: 7,
        },
        { ...structuralPin('attempt-r1', 'claim-r4', 'TARGET'), relationship_type: 'RESULT' },
      ],
    },
    (id) => ({
      title: id,
      href: `/${id}`,
      objectId: id.startsWith('claim') ? 'claim-object' : 'lemma-object',
    }),
  );
  expect(view).toMatchObject({
    attemptId: 'attempt-object',
    reportedProgress: 'PARTIAL',
    findings: 'Need a lemma',
    target: { revisionId: 'claim-r3' },
    resultingRevision: { revisionId: 'claim-r4' },
  });
  expect(view?.evidence[0]).toMatchObject({
    role: 'SUPPORTS',
    revision: { revisionId: 'lemma-r1' },
  });
});

it('maps server-owned note authority and summary freshness without inference', () => {
  const note = mapHumanNote(
    {
      object_id: 'proof-object',
      owner_user_id: 'ada-user',
      owner_display_name: 'Ada',
      can_edit: false,
      current_revision: {
        id: 'note-r1',
        object_id: 'proof-object',
        number: 1,
        base_revision_id: null,
        body_md: 'Private context',
        author_display_name: 'Ada',
        created_at: '2026-09-07T00:00:00Z',
      },
    },
    [],
  );
  const summary = mapAuthoredSummary(
    {
      object_id: 'proof-object',
      owner_display_name: 'Ada',
      current_revision: {
        id: 'summary-r1',
        object_id: 'proof-object',
        number: 1,
        base_revision_id: null,
        body_md: 'A stale synthesis',
        source_object_version_ids: ['claim-r1'],
        fresh: false,
        author_display_name: 'Ada',
        actor_kind: 'HUMAN',
        agent_display_name: null,
        created_at: '2026-09-07T00:00:00Z',
      },
    },
    (revisionId) => ({ title: 'Tree claim', href: `/${revisionId}`, objectId: 'claim' }),
  );

  expect(note).toMatchObject({ ownerId: 'ada-user', owner: 'Ada', canEdit: false });
  expect(summary).toMatchObject({ fresh: false, sources: [{ title: 'Tree claim' }] });
});
