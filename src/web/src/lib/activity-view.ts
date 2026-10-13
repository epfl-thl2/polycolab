// Browser view models; history-api maps the generated activity API types.
export type ActivityWindow = 'day' | 'week' | 'month';
export type ActivityKind =
  'statement' | 'contribution' | 'attempt' | 'proof' | 'revision' | 'comment' | 'evidence';
export type ActivityFilters = {
  window: ActivityWindow;
  actor: 'all' | 'human' | 'agent';
  kind: 'all' | ActivityKind;
};
export type SubmissionView = {
  id: string;
  submissionNumber?: number;
  objectKind?: string;
  actionLabel?: string;
  title: string;
  summary: string;
  kind: ActivityKind;
  actorKind: 'human' | 'agent';
  author: string;
  authorHref?: string;
  sponsor?: string;
  project: string;
  createdAt: string;
  revisionLabel: string;
  revisionHref?: string;
  projectHref?: string;
};
export type ActiveProjectView = {
  id: string;
  name: string;
  description: string;
  contributors: number;
  submissions: number;
  attempts: number;
  comments: number;
  lastActiveAt: string;
  href?: string;
};
export type ActivityPage<T> = { items: T[]; nextCursor?: string };
export interface ActivitySource {
  submissions(filters: ActivityFilters, cursor?: string): Promise<ActivityPage<SubmissionView>>;
  projects(window: ActivityWindow, cursor?: string): Promise<ActivityPage<ActiveProjectView>>;
}
export const activityKinds: Record<ActivityKind, string> = {
  statement: 'Statement',
  contribution: 'Contribution',
  attempt: 'Attempt',
  proof: 'Proof sketch',
  revision: 'Revision',
  comment: 'Comment',
  evidence: 'Evidence',
};
export const activityWindows: Record<ActivityWindow, string> = {
  day: 'Past 24 hours',
  week: 'Past 7 days',
  month: 'Past 30 days',
};
