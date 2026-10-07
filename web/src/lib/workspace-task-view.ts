import type { AgentSession } from './agent-sessions-api';

export function taskConversations(sessions: AgentSession[], taskId?: string) {
  return sessions
    .filter((session) => session.task_id === taskId || (!taskId && !session.task_id))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
}

export function conversationStatus(session: AgentSession) {
  const run = session.latest_run;
  if (!run) return session.status === 'ARCHIVED' ? 'Archived' : 'Ready';
  if (
    run.cancel_requested_at &&
    ['QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING'].includes(run.status)
  )
    return 'Cancelling';
  return run.status.toLowerCase().replaceAll('_', ' ');
}

export function taskActivity(sessions: AgentSession[]) {
  const running = sessions.filter(
    (session) =>
      session.latest_run &&
      ['CLAIMED', 'RUNNING', 'CANCELLING'].includes(session.latest_run.status),
  ).length;
  const waiting = sessions.filter((session) => session.latest_run?.status === 'QUEUED').length;
  return [running ? `${running} running` : '', waiting ? `${waiting} waiting` : '']
    .filter(Boolean)
    .join(' · ');
}
