// ── Types ─────────────────────────────────────────────────────────────────────

export interface TreeItem {
  path: string;
  type: "file" | "dir";
  size?: number;
}

export interface TreeNode {
  name: string;
  path: string;
  type: "file" | "dir";
  children: TreeNode[];
}

// ── Build nested tree ─────────────────────────────────────────────────────────

export function buildTree(items: TreeItem[]): TreeNode[] {
  const root: TreeNode[] = [];
  const map: Record<string, TreeNode> = {};

  // Sort: dirs first, then alphabetical
  const sorted = [...items].sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.path.localeCompare(b.path);
  });

  for (const item of sorted) {
    const parts = item.path.split("/");
    const name = parts[parts.length - 1];
    const node: TreeNode = { name, path: item.path, type: item.type, children: [] };
    map[item.path] = node;

    if (parts.length === 1) {
      root.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      if (map[parentPath]) {
        map[parentPath].children.push(node);
      } else {
        root.push(node);
      }
    }
  }

  return root;
}

export interface CommitEntry {
  sha: string;
  message: string;
  author: string;
  date: string;
}
