import type { Role } from './research-api';

export function canWriteResearch(role: Role, archived: boolean): boolean {
  return !archived && (role === 'OWNER' || role === 'CONTRIBUTOR');
}

export function restrictionMessage(role: Role, archived: boolean): string | undefined {
  if (archived)
    return 'This project is archived. Research is available to read, but cannot be changed.';
  if (role === 'READ_ONLY') return 'Your project role permits reading but not changing research.';
  return undefined;
}
