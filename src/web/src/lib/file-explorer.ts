export type ExplorerNode = {
  name: string;
  path: string;
  directory: boolean;
  children: ExplorerNode[];
};

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
