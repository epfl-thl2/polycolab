import { describe, expect, it } from 'vitest';
import {
  defaultWorkspaceLayout,
  parseWorkspaceLayout,
} from '../../../web/src/lib/workspace-layout';
describe('workspace layout preferences', () => {
  it('restores widths and collapsed rails', () => {
    const preferences = { leftWidth: 240, rightShare: 0.52, leftClosed: true, rightClosed: true };
    expect(parseWorkspaceLayout(JSON.stringify(preferences))).toEqual(preferences);
  });
  it('falls back safely when storage is missing or malformed', () => {
    for (const value of [null, '{', 'null', '[]', '{}'])
      expect(parseWorkspaceLayout(value)).toEqual(defaultWorkspaceLayout);
  });
  it('clamps old preferences and ignores invalid field types', () => {
    expect(parseWorkspaceLayout('{"leftWidth":900,"rightShare":0.05,"leftClosed":"true"}')).toEqual(
      { leftWidth: 340, rightShare: 0.2, leftClosed: false, rightClosed: false },
    );
  });
});
