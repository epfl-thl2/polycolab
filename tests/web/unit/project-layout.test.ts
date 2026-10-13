import { describe, expect, it } from 'vitest';
import { defaultProjectLayout, parseProjectLayout } from '../../../src/web/src/lib/project-layout';
describe('project layout preferences', () => {
  it('restores widths and collapsed rails', () => {
    const preferences = { leftWidth: 240, rightShare: 0.52, leftClosed: true, rightClosed: true };
    expect(parseProjectLayout(JSON.stringify(preferences))).toEqual(preferences);
  });
  it('falls back safely when storage is missing or malformed', () => {
    for (const value of [null, '{', 'null', '[]', '{}'])
      expect(parseProjectLayout(value)).toEqual(defaultProjectLayout);
  });
  it('clamps old preferences and ignores invalid field types', () => {
    expect(parseProjectLayout('{"leftWidth":900,"rightShare":0.05,"leftClosed":"true"}')).toEqual({
      leftWidth: 340,
      rightShare: 0.2,
      leftClosed: false,
      rightClosed: false,
    });
  });
});

it('migrates the saved workspace layout once and gives the project key precedence', async () => {
  const { readProjectLayout, projectLayoutKey } =
    await import('../../../src/web/src/lib/project-layout');
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
  };
  storage.setItem(
    'polycolab.workspace-layout.v1',
    JSON.stringify({ leftWidth: 310, leftClosed: true }),
  );
  expect(readProjectLayout(storage).leftWidth).toBe(310);
  expect(storage.getItem('polycolab.workspace-layout.v1')).toBeNull();
  storage.setItem('polycolab.workspace-layout.v1', JSON.stringify({ leftWidth: 220 }));
  expect(readProjectLayout(storage).leftWidth).toBe(310);
  expect(storage.getItem(projectLayoutKey)).not.toBeNull();
});
