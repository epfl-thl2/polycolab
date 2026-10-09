import type { components } from '$lib/api-client';

type Kind = components['schemas']['ObjectKind'];
export const profileKindLabels: Record<Kind, string> = {
  PROBLEM: 'Problem',
  DEFINITION: 'Definition',
  STATEMENT: 'Statement',
  PROOF: 'Proof',
  ATTEMPT: 'Research attempt',
  NOTE: 'Note',
  FORMALIZATION: 'Formalization',
};
export const profileGroups = [
  { id: 'research', label: 'Research', kinds: ['PROBLEM', 'DEFINITION', 'STATEMENT', 'NOTE'] },
  { id: 'proofs', label: 'Proofs', kinds: ['PROOF'] },
  { id: 'attempts', label: 'Attempts', kinds: ['ATTEMPT'] },
  { id: 'formalizations', label: 'Formalizations', kinds: ['FORMALIZATION'] },
] as const;
export type ProfileFilter = 'all' | (typeof profileGroups)[number]['id'];
export function matchesProfileGroup(kind: Kind, filter: ProfileFilter) {
  return (
    filter === 'all' ||
    profileGroups.some(
      (group) => group.id === filter && (group.kinds as readonly string[]).includes(kind),
    )
  );
}
