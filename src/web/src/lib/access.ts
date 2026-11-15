import type { Role } from './projects-api';

export function canWriteProject(role: Role, archived: boolean): boolean {
  return !archived && (role === 'OWNER' || role === 'EDITOR');
}

export function restrictionMessage(role: Role, archived: boolean): string | undefined {
  if (archived)
    return 'This project is archived. Project files are available to read, but cannot be changed.';
  if (role === 'VIEWER')
    return 'Your project role permits reading but not changing project files.';
  return undefined;
}
