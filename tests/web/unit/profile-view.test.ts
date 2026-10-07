import { expect, it } from 'vitest';
import {
  matchesProfileGroup,
  profileGroups,
  profileKindLabels,
} from '../../../web/src/lib/profile-view';

it('assigns every research kind to exactly one summary/filter category', () => {
  for (const kind of Object.keys(profileKindLabels) as Array<keyof typeof profileKindLabels>) {
    expect(profileGroups.filter((group) => matchesProfileGroup(kind, group.id))).toHaveLength(1);
    expect(matchesProfileGroup(kind, 'all')).toBe(true);
  }
  expect(matchesProfileGroup('PROOF', 'proofs')).toBe(true);
  expect(matchesProfileGroup('FORMALIZATION', 'formalizations')).toBe(true);
  expect(matchesProfileGroup('NOTE', 'research')).toBe(true);
});

import {
  contributionCalendar,
  contributionDay,
  contributionDays,
  validHistoryDay,
} from '../../../web/src/lib/contribution-history';

it('counts unique loaded revisions on UTC days without inventing dates for missing timestamps', () => {
  const record = (object_version_id: string, created_at?: string) => ({
    record: { object_version_id, created_at },
  });
  const days = contributionDays([
    record('one', '2024-02-29T23:30:00-02:00'),
    record('one', '2024-02-29T23:30:00-02:00'),
    record('two', '2024-03-01T12:00:00Z'),
    record('three', '2024-02-29T10:00:00Z'),
    record('missing'),
    record('invalid', 'unknown'),
  ]);
  expect([...days]).toEqual([
    ['2024-03-01', 2],
    ['2024-02-29', 1],
  ]);
  expect(contributionDay('invalid')).toBeUndefined();
  expect(validHistoryDay('2023-02-29')).toBeUndefined();
  expect(validHistoryDay('2024-02-29')).toBe('2024-02-29');
});

it('lays out complete leap and non-leap calendars with correct weekday alignment', () => {
  const leap = contributionCalendar(2024, new Map([['2024-02-29', 8]]));
  expect(leap).toHaveLength(366);
  expect(leap[0]).toMatchObject({ day: '2024-01-01', column: 1, row: 3, month: 'Jan' });
  expect(leap.find((day) => day.day === '2024-02-29')).toMatchObject({
    count: 8,
    level: 4,
    row: 6,
  });
  expect(leap.filter((day) => day.month)).toHaveLength(12);
  const ordinary = contributionCalendar(2023, new Map());
  expect(ordinary).toHaveLength(365);
  expect(ordinary[0]).toMatchObject({ row: 2 });
  expect(ordinary.at(-1)?.day).toBe('2023-12-31');
});

it('counts separate contributions to one revision and deduplicates multi-output events', () => {
  const event = (contribution_id: string, object_version_id: string) => ({
    contribution_id,
    record: { object_version_id, created_at: '2026-09-11T10:00:00Z' },
  });
  expect([
    ...contributionDays([
      event('create', 'r1'),
      event('comment', 'r1'),
      event('proof', 'r2'),
      event('proof', 'r3'),
    ]),
  ]).toEqual([['2026-09-11', 3]]);
});
