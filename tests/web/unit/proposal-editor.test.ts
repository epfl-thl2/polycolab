import { describe, expect, it } from 'vitest';
import {
  editProposalText,
  proposalAcceptanceEdit,
  proposalTextFields,
  proposalTextValue,
} from '../../../web/src/lib/proposal-editor';

describe('complete-snapshot proposal editor', () => {
  const proposal = {
    kind: 'CREATE_OBJECT_VERSION',
    object_id: 'object-1',
    expected_current_object_version_id: 'version-1',
    snapshot: {
      kind: 'ATTEMPT',
      content: {
        title: 'A failed reduction',
        content_md: 'Original approach',
        assumptions_md: 'Finite graphs',
        reported_outcome: 'FAILED',
        explanation_md: null,
        outcome: 'FAILED',
        findings_md: 'The premise does not survive reduction',
      },
      structural_relationships: [
        { relationship_type: 'TARGET', target_object_version_id: 'claim-v2' },
        {
          relationship_type: 'EVIDENCE',
          target_object_version_id: 'computation-v1',
          position: 7,
          evidence_role: 'SUPPORTING',
        },
      ],
      change_summary: null,
    },
  };

  it('edits nested text without mutating the proposal or dropping exact pins and metadata', () => {
    const original = structuredClone(proposal);
    const result = editProposalText(
      proposal,
      ['snapshot', 'content', 'content_md'],
      'Reviewed approach',
    );
    expect(result).toEqual({
      ...proposal,
      snapshot: {
        ...proposal.snapshot,
        content: { ...proposal.snapshot.content, content_md: 'Reviewed approach' },
      },
    });
    expect(proposal).toEqual(original);
    expect(proposalTextValue(result, ['snapshot', 'content', 'content_md'])).toBe(
      'Reviewed approach',
    );
    expect(proposalTextFields(result).map((field) => field.label)).toContain('Findings (Markdown)');
  });

  it('supports explicitly filling nullable text without changing the outcome', () => {
    const result = editProposalText(
      proposal,
      ['snapshot', 'content', 'explanation_md'],
      'A counterexample remains',
    );
    expect(result.snapshot).toMatchObject({
      content: { outcome: 'FAILED', explanation_md: 'A counterexample remains' },
    });
    expect(proposalTextValue(proposal, ['snapshot', 'change_summary'])).toBe('');
  });

  it.each([
    ['expected_current_object_version_id'],
    ['snapshot', 'content', 'outcome'],
    ['snapshot', 'structural_relationships'],
    ['__proto__', 'polluted'],
  ])('does not allow a text control to rewrite protected path %j', (...path) => {
    expect(() => editProposalText(proposal, path, 'changed')).toThrow('not editable text');
  });

  it('preserves symmetric endpoints when editing a relationship description', () => {
    const relation = {
      kind: 'CREATE_RELATIONSHIP',
      relationship: {
        direction: 'BIDIRECTIONAL',
        relationship_type: 'EQUIVALENT_TO',
        first_object_version_id: 'a',
        second_object_version_id: 'b',
        description: null,
      },
    };
    expect(
      editProposalText(relation, ['relationship', 'description'], 'Proposed equivalence'),
    ).toEqual({
      ...relation,
      relationship: { ...relation.relationship, description: 'Proposed equivalence' },
    });
  });

  it('retains historical payload editing during the HTTP transition', () => {
    const legacy = {
      kind: 'CREATE_REVISION',
      base_revision_id: 'old',
      title: 'Old',
      content_md: 'Old text',
    };
    expect(editProposalText(legacy, ['content_md'], 'Reviewed')).toEqual({
      ...legacy,
      content_md: 'Reviewed',
    });
  });

  it('accepts unchanged and restored drafts without resubmitting their payload', () => {
    expect(proposalAcceptanceEdit(proposal, JSON.stringify(proposal, null, 2))).toEqual({});
    const reordered = Object.fromEntries(Object.entries(proposal).reverse());
    expect(proposalAcceptanceEdit(proposal, JSON.stringify(reordered))).toEqual({});
    const changed = editProposalText(proposal, ['snapshot', 'content', 'title'], 'Reviewed');
    expect(proposalAcceptanceEdit(proposal, JSON.stringify(changed))).toEqual({ payload: changed });
    const restored = editProposalText(
      changed,
      ['snapshot', 'content', 'title'],
      proposal.snapshot.content.title,
    );
    expect(proposalAcceptanceEdit(proposal, JSON.stringify(restored))).toEqual({});
  });

  it('does not treat changed nulls or relationship order as an unchanged acceptance', () => {
    const changed = structuredClone(proposal);
    changed.snapshot.structural_relationships.reverse();
    expect(proposalAcceptanceEdit(proposal, JSON.stringify(changed))).toHaveProperty('payload');
    expect(proposalAcceptanceEdit({ text: null }, '{"text":""}')).toEqual({
      payload: { text: '' },
    });
    expect(() => proposalAcceptanceEdit(proposal, '[]')).toThrow(SyntaxError);
  });
});
