/** Calendar counts for loaded canonical contributions and version-based demo records. */
export type DatedContribution = {
  contribution_id?: string | null;
  record: { object_version_id: string; created_at?: string | null };
};

export function contributionDay(timestamp?: string | null): string | undefined {
  if (!timestamp) return undefined;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString().slice(0, 10);
}

export function validHistoryDay(value: string | null): string | undefined {
  return value &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    value >= '1970-01-01' &&
    value <= new Date().toISOString().slice(0, 10) &&
    contributionDay(value) === value
    ? value
    : undefined;
}

export function contributionDays(items: readonly DatedContribution[]) {
  const days = new Map<string, number>();
  const seen = new Set<string>();
  for (const { record, contribution_id } of items) {
    const identity = contribution_id ?? record.object_version_id;
    if (seen.has(identity)) continue;
    seen.add(identity);
    const day = contributionDay(record.created_at);
    if (day) days.set(day, (days.get(day) ?? 0) + 1);
  }
  return days;
}

export function contributionCalendar(year: number, counts: ReadonlyMap<string, number>) {
  const start = new Date(Date.UTC(year, 0, 1));
  const offset = start.getUTCDay();
  const end = Date.UTC(year + 1, 0, 1);
  const days = [];
  for (let time = start.getTime(), index = 0; time < end; time += 86_400_000, index++) {
    const date = new Date(time);
    const day = date.toISOString().slice(0, 10);
    const count = counts.get(day) ?? 0;
    days.push({
      day,
      count,
      column: Math.floor((index + offset) / 7) + 1,
      row: date.getUTCDay() + 2,
      month:
        date.getUTCDate() === 1
          ? date.toLocaleString('en', { month: 'short', timeZone: 'UTC' })
          : '',
      level: count === 0 ? 0 : count === 1 ? 1 : count < 4 ? 2 : count < 8 ? 3 : 4,
    });
  }
  return days;
}

export function historyDateLabel(day: string) {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}
