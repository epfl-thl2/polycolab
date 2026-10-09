/** Text-only edits preserve the complete proposal and its exact structural pins. */
import type { components } from '$lib/api-client';

export type ProposalPayload = Record<string, unknown>;
type ProposalEdit = NonNullable<components['schemas']['ProposalBatchDecision']['payload']>;
export type ProposalTextField = { path: string[]; label: string; value: string };

function record(value: unknown): value is ProposalPayload {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right))
    return (
      left.length === right.length && left.every((item, index) => sameJson(item, right[index]))
    );
  if (record(left) && record(right)) {
    const keys = Object.keys(left);
    return (
      keys.length === Object.keys(right).length &&
      keys.every((key) => Object.hasOwn(right, key) && sameJson(left[key], right[key]))
    );
  }
  return false;
}

export function proposalAcceptanceEdit(
  original: ProposalPayload,
  draft: string,
): { payload?: ProposalEdit } {
  const parsed: unknown = JSON.parse(draft);
  if (!record(parsed)) throw new SyntaxError('A proposal change must be a JSON object.');
  // This preserves the edited JSON; the HTTP boundary validates the full command,
  // including historical snapshots that may not meet current write requirements.
  return sameJson(original, parsed) ? {} : { payload: parsed as ProposalEdit };
}

export function proposalTextFields(payload: ProposalPayload): ProposalTextField[] {
  const fields: ProposalTextField[] = [];
  function add(source: ProposalPayload, prefix: string[], names: Record<string, string>) {
    for (const [key, label] of Object.entries(names)) {
      if (typeof source[key] === 'string' || source[key] === null)
        fields.push({ path: [...prefix, key], label, value: String(source[key] ?? '') });
    }
  }
  if (record(payload.snapshot) && record(payload.snapshot.content)) {
    add(payload.snapshot.content, ['snapshot', 'content'], {
      title: 'Title',
      content_md: 'Research text (Markdown)',
      assumptions_md: 'Assumptions (Markdown)',
      explanation_md: 'Explanation (Markdown)',
      findings_md: 'Findings (Markdown)',
    });
    add(payload.snapshot, ['snapshot'], { change_summary: 'Change summary' });
  } else {
    // Comments use body_md; retain legacy text rendering for older local drafts.
    add(payload, [], {
      title: 'Title',
      content_md: 'Research text (Markdown)',
      body_md: 'Comment (Markdown)',
      rationale: 'Rationale',
    });
  }
  if (record(payload.relationship))
    add(payload.relationship, ['relationship'], { description: 'Relationship description' });
  return fields;
}

export function proposalTextValue(payload: ProposalPayload, path: string[]): string {
  let value: unknown = payload;
  for (const key of path) value = record(value) ? value[key] : undefined;
  return typeof value === 'string' ? value : '';
}

export function editProposalText(
  payload: ProposalPayload,
  path: string[],
  value: string,
): ProposalPayload {
  if (
    !proposalTextFields(payload).some(
      (field) => JSON.stringify(field.path) === JSON.stringify(path),
    )
  )
    throw new Error('This proposal field is not editable text.');
  const result = structuredClone(payload);
  let target = result;
  for (const key of path.slice(0, -1)) {
    const nested = target[key];
    if (!record(nested)) throw new Error('Invalid proposal field path.');
    target = nested;
  }
  target[path[path.length - 1]] = value;
  return result;
}
