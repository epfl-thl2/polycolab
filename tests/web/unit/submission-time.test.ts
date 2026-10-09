import { afterEach, expect, it, vi } from 'vitest';
import {
  deviceSubmissionClock,
  utcSubmissionClock,
} from '../../../src/web/src/lib/submission-time';

afterEach(() => vi.restoreAllMocks());

it('uses the device zone and accounts for daylight saving time', () => {
  const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
  vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (
    this: Intl.DateTimeFormat,
  ) {
    return { ...resolved.call(this), timeZone: 'Europe/Zurich' };
  });
  const clock = deviceSubmissionClock();
  expect(clock.timeZone).toBe('Europe/Zurich');
  expect(clock.local).toBe(true);
  expect(clock.format('2026-09-15T10:00:00Z')).toBe('2026-09-15 12:00:00');
  expect(clock.format('2026-01-15T10:00:00Z')).toBe('2026-01-15 11:00:00');
});

it('falls back to UTC when device time zone detection fails', () => {
  vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(() => {
    throw new Error('Time zone unavailable');
  });
  const clock = deviceSubmissionClock();
  expect(clock).toBe(utcSubmissionClock);
  expect(clock.format('2026-09-15T12:00:00+02:00')).toBe('2026-09-15 10:00:00');
});
