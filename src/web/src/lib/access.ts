import type { Role } from './projects-api';

export function canWriteProject(role: Role, archived: boolean): boolean {
  return !archived && (role === 'OWNER' || role === 'CONTRIBUTOR');
}

export function restrictionMessage(role: Role, archived: boolean): string | undefined {
  if (archived)
    return 'This project is archived. Project files are available to read, but cannot be changed.';
  if (role === 'READ_ONLY')
    return 'Your project role permits reading but not changing project files.';
  return undefined;
}
