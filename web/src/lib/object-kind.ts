/** Read compatibility for historical API responses during the kind migration. */
export function canonicalObjectKind(kind: string): string {
  const aliases: Record<string, string> = {
    CLAIM: 'STATEMENT',
    PROOF_SKETCH: 'PROOF',
    IDEA: 'NOTE',
    DISCUSSION: 'NOTE',
    COUNTEREXAMPLE: 'NOTE',
    COMPUTATION: 'NOTE',
  };
  return aliases[kind] ?? kind;
}
