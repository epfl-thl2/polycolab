import type { ObjectVersion } from './research-api';

export function objectProgress(version?: ObjectVersion) {
  if (!version) return undefined;
  const progress =
    version.kind === 'PROOF'
      ? version.content.reported_progress
      : version.kind === 'ATTEMPT'
        ? version.content.outcome
        : version.content.reported_outcome;
  switch (progress) {
    case 'IN_PROGRESS':
      return { label: 'In progress', color: '--status-progress' };
    case 'POTENTIAL':
      return { label: 'Potential', color: '--status-attention' };
    case 'PARTIAL':
      return { label: 'Partial', color: '--status-attention' };
    case 'STALLED':
      return { label: 'Stalled', color: '--status-attention' };
    case 'COMPLETE':
    case 'SUCCEEDED':
      return { label: 'Complete', color: '--status-complete' };
    case 'FAILED':
      return { label: 'Failed', color: '--status-issues' };
    default:
      return undefined;
  }
}
