export type ExplorerNode = {
  name: string;
  path: string;
  directory: boolean;
  children: ExplorerNode[];
};

export type ExplorerViewState = {
  filter: string;
  collapsed: string[];
  scrollTop: number;
  lastSelected: string;
  showDotfiles: boolean;
  showIgnoredFiles: boolean;
};

export function createExplorerView(): ExplorerViewState {
  return {
    filter: '',
    collapsed: [],
    scrollTop: 0,
    lastSelected: '',
    showDotfiles: false,
    showIgnoredFiles: false,
  };
}

export type FileChange = { path: string; status: 'added' | 'modified' | 'deleted' };

export function fileDecorations(paths: string[], changes: FileChange[]) {
  const existing = new Set(paths);
  const folders = new Set(
    paths.flatMap((path) => {
      const parts = path.split('/');
      return parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'));
    }),
  );
  const result = new Map<string, FileChange['status']>();
  const priority = { added: 1, modified: 2, deleted: 3 };
  for (const { path, status } of changes) {
    if (existing.has(path) && status !== 'deleted') result.set(path, status);
    const parts = path.split('/');
    for (let index = 1; index < parts.length; index++) {
      const folder = parts.slice(0, index).join('/');
      const previous = result.get(folder);
      if (folders.has(folder) && (!previous || priority[status] > priority[previous]))
        result.set(folder, status);
    }
  }
  return result;
}

/** Git stores file paths; folders are derived and never need placeholder files. */
export function fileTree(paths: string[]): ExplorerNode[] {
  const root: ExplorerNode[] = [];
  for (const path of paths) {
    const parts = path.split('/');
    let children = root;
    for (let index = 0; index < parts.length; index++) {
      const name = parts[index]!;
      const directory = index < parts.length - 1;
      let node = children.find((item) => item.name === name && item.directory === directory);
      if (!node) {
        node = { name, path: parts.slice(0, index + 1).join('/'), directory, children: [] };
        children.push(node);
      }
      children = node.children;
    }
  }
  function sort(nodes: ExplorerNode[]) {
    nodes.sort((a, b) => Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name));
    for (const node of nodes) sort(node.children);
  }
  sort(root);
  return root;
}
