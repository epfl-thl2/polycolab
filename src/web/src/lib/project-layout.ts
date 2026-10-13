export const projectLayoutKey = 'polycolab.project-layout.v1';
export const defaultProjectLayout = {
  leftWidth: 280,
  rightShare: 0.4,
  leftClosed: false,
  rightClosed: false,
};
export function parseProjectLayout(raw: string | null) {
  try {
    const value = JSON.parse(raw ?? '{}');
    return {
      leftWidth:
        typeof value?.leftWidth === 'number' && Number.isFinite(value.leftWidth)
          ? Math.max(216, Math.min(340, value.leftWidth))
          : 280,
      rightShare:
        typeof value?.rightShare === 'number' && Number.isFinite(value.rightShare)
          ? Math.max(0.2, Math.min(0.6, value.rightShare))
          : 0.4,
      leftClosed: value?.leftClosed === true,
      rightClosed: value?.rightClosed === true,
    };
  } catch {
    return { ...defaultProjectLayout };
  }
}

// Read the old key once, then persist and use the canonical project preference.
export function readProjectLayout(storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
  const current = storage.getItem(projectLayoutKey);
  if (current !== null) return parseProjectLayout(current);
  const legacyKey = 'polycolab.workspace-layout.v1';
  const legacy = storage.getItem(legacyKey);
  const layout = parseProjectLayout(legacy);
  if (legacy !== null) {
    storage.setItem(projectLayoutKey, JSON.stringify(layout));
    storage.removeItem(legacyKey);
  }
  return layout;
}
