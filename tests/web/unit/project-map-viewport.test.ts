import { describe, expect, it } from 'vitest';
import { localMapViewport } from '../../../src/web/src/lib/project-map-viewport';

const layout = {
  positions: {
    focus: { x: 100, y: 100 },
    neighbor: { x: 400, y: 100 },
    distant: { x: 10000, y: 10000 },
  },
  sizes: {
    focus: { width: 200, height: 60 },
    neighbor: { width: 200, height: 60 },
    distant: { width: 200, height: 60 },
  },
};

describe('local map framing', () => {
  it('fits direct neighbors with padding while keeping focus centered and ignoring unrelated nodes', () => {
    const view = localMapViewport(layout, 'focus', ['focus', 'neighbor'], 800, 500)!;
    expect(view).toEqual({ x: 200, y: 130, zoom: 0.7 });
    const right = (600 - view.x) * view.zoom + 400;
    expect(right).toBeCloseTo(800 * 0.85);
  });
  it('uses a readable default for isolated nodes and ignores missing neighbors', () => {
    expect(localMapViewport(layout, 'focus', ['missing'], 800, 500)?.zoom).toBe(0.9);
  });
  it('caps zoom-out for widely spread neighborhoods and zoom-in for small neighborhoods', () => {
    expect(localMapViewport(layout, 'focus', ['distant'], 800, 500)?.zoom).toBe(0.65);
    expect(localMapViewport(layout, 'focus', ['neighbor'], 1600, 900)?.zoom).toBe(1);
  });
  it('keeps the selected node visible in narrow viewports', () => {
    expect(localMapViewport(layout, 'focus', ['distant'], 100, 100)?.zoom).toBe(0.35);
  });
  it('does not move for missing focus or an unmeasured viewport', () => {
    expect(localMapViewport(layout, 'missing', [], 800, 500)).toBeUndefined();
    expect(localMapViewport(layout, 'focus', [], 0, 500)).toBeUndefined();
  });
});
