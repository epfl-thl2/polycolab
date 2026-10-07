export const workspaceLayoutKey = 'polycolab.workspace-layout.v1';
export const defaultWorkspaceLayout = {
  leftWidth: 280,
  rightShare: 0.4,
  leftClosed: false,
  rightClosed: false,
};
export function parseWorkspaceLayout(raw: string | null) {
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
    return { ...defaultWorkspaceLayout };
  }
}
