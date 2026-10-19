import { getContext } from 'svelte';

export type ProjectUtility = 'settings' | 'agent-connect' | 'information';
export type ProjectDialogController = { open: (utility: ProjectUtility) => void };
export const projectDialogsKey = Symbol('project-dialogs');
export const projectDialogs = () =>
  getContext<ProjectDialogController | undefined>(projectDialogsKey);

export function projectUtility(projectId: string, pathname: string): ProjectUtility | undefined {
  if (pathname === `/projects/${projectId}/settings`) return 'settings';
  if (pathname === `/projects/${projectId}/agent-connect`) return 'agent-connect';
}
