import { describe, expect, it } from 'vitest';
import {
  proofStructureWrite,
  researchAttemptWrite,
  newVersionSnapshot,
} from '../../../src/web/src/lib/research-record-draft';

describe('structured research record drafts', () => {
  const draft = {
    kind: 'NOTE' as const,
    title: 'Research',
    content_md: 'Full content',
    assumptions_md: 'None',
    reported_outcome: null,
    change_summary: '',
  };

  it('creates a full ordinary snapshot with an explicit empty relationship set', () => {
    expect(newVersionSnapshot(draft, [])).toEqual({
      kind: 'NOTE',
      change_summary: null,
      structural_relationships: [],
      content: {
        title: 'Research',
        content_md: 'Full content',
        assumptions_md: 'None',
        reported_outcome: null,
        explanation_md: null,
      },
    });
  });

  it('creates proof snapshots with canonical pinned relationships and ordered premises', () => {
    const snapshot = newVersionSnapshot(
      { ...draft, kind: 'PROOF' },
      ['claim-r1'],
      proofStructureWrite('claim-r1', ['premise-r2', 'premise-r1'], 'PARTIAL'),
    );
    expect(snapshot.content).toMatchObject({ reported_progress: 'PARTIAL' });
    expect(snapshot.structural_relationships).toEqual([
      { relationship_type: 'ATTACHMENT', target_object_version_id: 'claim-r1' },
      { relationship_type: 'CONCLUSION', target_object_version_id: 'claim-r1' },
      { relationship_type: 'PREMISE', target_object_version_id: 'premise-r2', position: 0 },
      { relationship_type: 'PREMISE', target_object_version_id: 'premise-r1', position: 1 },
    ]);
    expect(snapshot).not.toHaveProperty('proof_sketch');
  });

  it('creates attempt snapshots with findings and typed evidence pins', () => {
    const snapshot = newVersionSnapshot(
      { ...draft, kind: 'ATTEMPT' },
      [],
      undefined,
      researchAttemptWrite('claim-r1', 'PARTIAL', 'Finding', 'result-r2', 'SUPPORTS: evidence-r3'),
    );
    expect(snapshot.content).toMatchObject({ outcome: 'PARTIAL', findings_md: 'Finding' });
    expect(snapshot.structural_relationships).toEqual([
      { relationship_type: 'TARGET', target_object_version_id: 'claim-r1' },
      { relationship_type: 'RESULT', target_object_version_id: 'result-r2' },
      {
        relationship_type: 'EVIDENCE',
        target_object_version_id: 'evidence-r3',
        position: 0,
        evidence_role: 'SUPPORTS',
      },
    ]);
    expect(snapshot).not.toHaveProperty('attempt');
  });

  it('does not invent missing proof or attempt structure', () => {
    expect(() => newVersionSnapshot({ ...draft, kind: 'PROOF' }, [])).toThrow(
      /explicit conclusion/,
    );
    expect(() => newVersionSnapshot({ ...draft, kind: 'ATTEMPT' }, [])).toThrow(/explicit target/);
  });
  it('preserves the ordered exact premise set and independent sketch progress', () => {
    expect(proofStructureWrite(' conclusion-r2 ', ['premise-r3', 'premise-r1'], 'PARTIAL')).toEqual(
      {
        conclusion_revision_id: 'conclusion-r2',
        premise_revision_ids: ['premise-r3', 'premise-r1'],
        reported_progress: 'PARTIAL',
      },
    );
  });

  it('maps attempt findings, result, and typed exact evidence', () => {
    expect(
      researchAttemptWrite(
        'target-r2',
        'FAILED',
        'The bound is too weak.',
        'result-r1',
        'INPUT: premise-r1\nCONTRADICTS: counterexample-r3',
      ),
    ).toEqual({
      target_revision_id: 'target-r2',
      outcome: 'FAILED',
      findings_md: 'The bound is too weak.',
      result_revision_id: 'result-r1',
      evidence: [
        { role: 'INPUT', revision_id: 'premise-r1' },
        { role: 'CONTRADICTS', revision_id: 'counterexample-r3' },
      ],
    });
  });

  it('rejects malformed evidence before sending a mutation', () => {
    expect(() => researchAttemptWrite('target', 'PARTIAL', 'finding', '', 'MAYBE: r1')).toThrow(
      /Invalid evidence line/,
    );
  });
});
