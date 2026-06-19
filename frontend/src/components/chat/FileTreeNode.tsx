"use client";

import { useState } from "react";
import { ChevronRight, ChevronDown, File, Folder, FolderOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TreeNode } from "@/lib/file-tree";

export function FileTreeNode({
  node,
  depth,
  selectedPath,
  modifiedPaths,
  onSelectFile,
  defaultOpen,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  modifiedPaths: Set<string>;
  onSelectFile: (path: string) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (node.type === "dir") {
    return (
      <div>
        <button
          className={cn(
            "flex items-center gap-1 w-full px-2 py-0.5 text-xs hover:bg-accent/30 transition-colors text-left rounded-sm",
          )}
          style={{ paddingLeft: `${8 + depth * 12}px` }}
          onClick={() => setOpen((v) => !v)}
        >
          {open
            ? <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
            : <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
          }
          {open
            ? <FolderOpen className="w-3 h-3 text-yellow-400/80 shrink-0" />
            : <Folder className="w-3 h-3 text-yellow-400/80 shrink-0" />
          }
          <span className="truncate flex-1">{node.name}</span>
        </button>
        {open && node.children.map((child) => (
          <FileTreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            modifiedPaths={modifiedPaths}
            onSelectFile={onSelectFile}
            defaultOpen={false}
          />
        ))}
      </div>
    );
  }

  const isModified = modifiedPaths.has(node.path);
  const isSelected = selectedPath === node.path;

  return (
    <button
      className={cn(
        "flex items-center gap-1 w-full px-2 py-0.5 text-xs transition-colors text-left rounded-sm",
        isSelected ? "bg-accent text-foreground" : "hover:bg-accent/30 text-muted-foreground hover:text-foreground",
      )}
      style={{ paddingLeft: `${8 + depth * 12}px` }}
      onClick={() => onSelectFile(node.path)}
    >
      <File className="w-3 h-3 shrink-0" />
      <span className="truncate flex-1">{node.name}</span>
      {isModified && (
        <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" title="Modified by agent" />
      )}
    </button>
  );
}
