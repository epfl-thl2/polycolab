import type { AgentEvent, AgentRun } from '../lib/agent-sessions-api';

/** Session SSE IDs are ordered (run queue sequence, event cursor) pairs. */
export function advancesCursor(previous: string | undefined, incoming: string): boolean {
  if (!/^\d+:\d+$/.test(incoming)) return false;
  if (!previous) return true;
  const [oldRun, oldEvent] = previous.split(':').map(Number);
  const [nextRun, nextEvent] = incoming.split(':').map(Number);
  return nextRun > oldRun || (nextRun === oldRun && nextEvent > oldEvent);
}
export function statusFromEvent(event: AgentEvent): AgentRun['status'] | undefined {
  const states: Record<string, AgentRun['status']> = {
    RUN_STARTED: 'RUNNING',
    CANCEL_REQUESTED: 'CANCELLING',
    RUN_COMPLETED: 'COMPLETED',
    RUN_CANCELLED: 'CANCELLED',
    RUN_FAILED: 'FAILED',
    RUN_TIMED_OUT: 'TIMED_OUT',
  };
  return states[event.kind];
}
