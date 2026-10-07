import type { MapLayout } from './workspace-map-layout';

/** Frame a one-hop neighborhood around its selected node, with a readable zoom floor. */
export function localMapViewport(
  layout: Pick<MapLayout, 'positions' | 'sizes'>,
  focusedId: string,
  neighborIds: readonly string[],
  width: number,
  height: number,
): { x: number; y: number; zoom: number } | undefined {
  const position = layout.positions[focusedId];
  const size = layout.sizes[focusedId];
  if (!position || !size || width <= 0 || height <= 0) return;
  const x = position.x + size.width / 2;
  const y = position.y + size.height / 2;
  let halfWidth = size.width / 2;
  let halfHeight = size.height / 2;
  let neighbors = 0;
  for (const id of new Set(neighborIds)) {
    if (id === focusedId) continue;
    const point = layout.positions[id];
    const bounds = layout.sizes[id];
    if (!point || !bounds) continue;
    neighbors += 1;
    halfWidth = Math.max(halfWidth, Math.abs(point.x - x), Math.abs(point.x + bounds.width - x));
    halfHeight = Math.max(halfHeight, Math.abs(point.y - y), Math.abs(point.y + bounds.height - y));
  }
  // Reserve 15% of each viewport dimension on either side.
  const availableWidth = width * 0.7;
  const availableHeight = height * 0.7;
  const fit = Math.min(availableWidth / (halfWidth * 2), availableHeight / (halfHeight * 2));
  const focusFit = Math.min(availableWidth / size.width, availableHeight / size.height);
  return {
    x,
    y,
    zoom: Math.min(focusFit, neighbors ? Math.min(1, Math.max(0.65, fit)) : 0.9),
  };
}
