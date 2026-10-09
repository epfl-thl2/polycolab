const utcTimestamp = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : date.toISOString().slice(0, 19).replace('T', ' ');
};

export const utcSubmissionClock = { timeZone: 'UTC', local: false, format: utcTimestamp };

export function deviceSubmissionClock() {
  try {
    const timeZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!timeZone) return utcSubmissionClock;
    const formatter = new Intl.DateTimeFormat('en', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
    return {
      timeZone,
      local: true,
      format(value: string) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'Unknown time';
        const parts = Object.fromEntries(
          formatter.formatToParts(date).map((part) => [part.type, part.value]),
        );
        return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
      },
    };
  } catch {
    return utcSubmissionClock;
  }
}
