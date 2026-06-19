"use client";
import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { skillsApi } from "@/lib/api";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  X, Plus, Trash2, FileText, Folder, ChevronRight, ChevronDown,
  Save, Loader2, FilePlus, Eye, Pencil, Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import toast from "react-hot-toast";

interface Skill {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  is_builtin: boolean;
  files?: Record<string, string>;
}

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: FileNode[];
}

// ─── File tree builder ────────────────────────────────────────────

function buildTree(files: Record<string, string>): FileNode[] {
  const root: FileNode[] = [];
  const dirMap: Record<string, FileNode> = {};

  const getOrCreateDir = (parts: string[], upTo: number): FileNode[] => {
    if (upTo === 0) return root;
    const dirPath = parts.slice(0, upTo).join("/");
    if (!dirMap[dirPath]) {
      const parent = getOrCreateDir(parts, upTo - 1);
      const node: FileNode = { name: parts[upTo - 1], path: dirPath, isDir: true, children: [] };
      dirMap[dirPath] = node;
      parent.push(node);
    }
    return dirMap[dirPath].children!;
  };

  const sorted = Object.keys(files).sort();
  for (const path of sorted) {
    const parts = path.split("/");
    const parent = getOrCreateDir(parts, parts.length - 1);
    parent.push({ name: parts[parts.length - 1], path, isDir: false });
  }

  return root;
}

function sortTree(nodes: FileNode[]): FileNode[] {
  return nodes
    .sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    })
    .map((n) => ({ ...n, children: n.children ? sortTree(n.children) : undefined }));
}

// ─── File tree node ───────────────────────────────────────────────

function TreeNode({
  node, depth, selected, onSelect, expanded, onToggle,
}: {
  node: FileNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  expanded: Set<string>;
  onToggle: (path: string) => void;
}) {
  const isExpanded = expanded.has(node.path);
  return (
    <div>
      <button
        onClick={() => node.isDir ? onToggle(node.path) : onSelect(node.path)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs rounded transition-colors",
          !node.isDir && selected === node.path
            ? "bg-primary/10 text-primary font-medium"
            : "hover:bg-accent/50 text-foreground"
        )}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {node.isDir ? (
          <>
            {isExpanded ? <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 shrink-0 text-muted-foreground" />}
            <Folder className="w-3.5 h-3.5 shrink-0 text-amber-400" />
          </>
        ) : (
          <>
            <span className="w-3 shrink-0" />
            <FileText className="w-3.5 h-3.5 shrink-0 text-blue-400" />
          </>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {node.isDir && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              expanded={expanded}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Language detection ───────────────────────────────────────────

function detectLang(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    md: "markdown", py: "python", ts: "typescript", tsx: "typescript",
    js: "javascript", jsx: "javascript", json: "json", yaml: "yaml",
    yml: "yaml", sh: "bash", bash: "bash", txt: "text", toml: "toml",
    css: "css", html: "html", sql: "sql",
  };
  return map[ext] ?? "text";
}

function isMarkdown(path: string) {
  return path.endsWith(".md") || path.endsWith(".mdx");
}

// ─── New file dialog ──────────────────────────────────────────────

function NewFileDialog({
  onConfirm, onCancel, prefix,
}: {
  onConfirm: (path: string) => void;
  onCancel: () => void;
  prefix?: string;
}) {
  const [value, setValue] = useState(prefix ? `${prefix}/` : "");
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      <Input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && value.trim()) onConfirm(value.trim());
          if (e.key === "Escape") onCancel();
        }}
        placeholder="path/to/file.md"
        className="h-6 text-xs font-mono py-0 px-1"
      />
      <button onClick={() => value.trim() && onConfirm(value.trim())} className="text-primary hover:text-primary/80">
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
      <button onClick={onCancel} className="text-muted-foreground hover:text-foreground">
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────

const DEFAULT_SKILL_MD = `# Skill: {name}

## Description
Describe what this skill does.

## Usage
Explain how agents should use this skill.

## Parameters
- \`param1\`: Description of param1

## Examples
\`\`\`
Example usage here
\`\`\`
`;

export function SkillDetailPanel({
  skill,
  onClose,
}: {
  skill: Skill;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editContent, setEditContent] = useState<string>("");
  const [isDirty, setIsDirty] = useState(false);
  const [previewMode, setPreviewMode] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addingFile, setAddingFile] = useState(false);

  const isFromFilesystem = skill.is_builtin || skill.id.startsWith("builtin:");

  const { data: fileTree, isLoading } = useQuery<{ files: Record<string, string> }>({
    queryKey: isFromFilesystem ? ["skill-builtin-files", skill.key] : ["skill-files", skill.id],
    queryFn: () =>
      isFromFilesystem
        ? skillsApi.builtinFiles(skill.key).then((r) => r.data)
        : skillsApi.files(skill.id).then((r) => r.data),
  });

  const rawFiles = fileTree?.files ?? skill.files ?? {};
  const files = isFromFilesystem
    ? Object.fromEntries(Object.entries(rawFiles).filter(([k]) => k !== "skill.json"))
    : rawFiles;
  const tree = sortTree(buildTree(files));

  // Auto-select SKILL.md if it exists, else first file
  useEffect(() => {
    if (!selectedPath) {
      const keys = Object.keys(files);
      const pref = keys.find((k) => k === "SKILL.md" || k === "skill.md") ?? keys[0];
      if (pref) {
        setSelectedPath(pref);
        setEditContent(files[pref]);
        setPreviewMode(isMarkdown(pref));
      }
    }
  }, [files, selectedPath]);

  const selectFile = useCallback((path: string) => {
    if (isDirty) {
      if (!confirm("Discard unsaved changes?")) return;
    }
    setSelectedPath(path);
    setEditContent(files[path] ?? "");
    setPreviewMode(isMarkdown(path));
    setIsDirty(false);
  }, [files, isDirty]);

  const toggleDir = (path: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });

  const saveFile = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      skillsApi.putFile(skill.id, path, content),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skill-files", skill.id] });
      setIsDirty(false);
      toast.success("File saved");
    },
    onError: () => toast.error("Failed to save file"),
  });

  const deleteFile = useMutation({
    mutationFn: (path: string) => skillsApi.deleteFile(skill.id, path),
    onSuccess: (_, path) => {
      qc.invalidateQueries({ queryKey: ["skill-files", skill.id] });
      if (selectedPath === path) { setSelectedPath(null); setEditContent(""); }
      toast.success("File deleted");
    },
    onError: () => toast.error("Failed to delete file"),
  });

  const createFile = async (path: string) => {
    const defaultContent = path === "SKILL.md" || path === "skill.md"
      ? DEFAULT_SKILL_MD.replace("{name}", skill.name)
      : path.endsWith(".md") ? `# ${path.split("/").pop()?.replace(".md", "")}\n\n`
      : "";
    await skillsApi.putFile(skill.id, path, defaultContent);
    qc.invalidateQueries({ queryKey: ["skill-files", skill.id] });
    setSelectedPath(path);
    setEditContent(defaultContent);
    setPreviewMode(isMarkdown(path));
    setIsDirty(false);
    setAddingFile(false);
    toast.success("File created");
  };

  const handleSave = () => {
    if (!selectedPath) return;
    saveFile.mutate({ path: selectedPath, content: editContent });
  };

  const CATEGORY_COLORS: Record<string, string> = {
    code:  "bg-blue-500/10 text-blue-400 border-blue-500/20",
    file:  "bg-amber-500/10 text-amber-400 border-amber-500/20",
    web:   "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    git:   "bg-violet-500/10 text-violet-400 border-violet-500/20",
    ai:    "bg-pink-500/10 text-pink-400 border-pink-500/20",
    custom:"bg-muted text-muted-foreground border-border",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex flex-col bg-background border-l border-border w-full max-w-4xl h-full shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold">{skill.name}</h2>
                <code className="text-xs text-muted-foreground font-mono">{skill.key}</code>
                <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", CATEGORY_COLORS[skill.category] ?? CATEGORY_COLORS.custom)}>
                  {skill.category}
                </Badge>
                {skill.is_builtin && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>}
              </div>
              {skill.description && <p className="text-xs text-muted-foreground mt-0.5">{skill.description}</p>}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="sm" variant="ghost"
              className="h-7 gap-1.5 text-xs"
              onClick={async () => {
                try {
                  const res = isFromFilesystem
                    ? await skillsApi.builtinExport(skill.key)
                    : await skillsApi.export(skill.id);
                  downloadBlob(res.data as Blob, `skill_${skill.key}.zip`);
                } catch { toast.error("Export failed"); }
              }}
            >
              <Download className="w-3.5 h-3.5" />Export
            </Button>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-accent text-muted-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {skill.is_builtin && Object.keys(files).length === 0 && !isLoading ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
            <FileText className="w-10 h-10 opacity-20" />
            <p className="text-sm">No documentation for this built-in skill.</p>
          </div>
        ) : (
          <div className="flex flex-1 overflow-hidden">
            {/* File tree sidebar */}
            <div className="w-56 border-r border-border flex flex-col shrink-0">
              <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Files</span>
                {!skill.is_builtin && (
                  <button
                    onClick={() => setAddingFile(true)}
                    className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                    title="New file"
                  >
                    <FilePlus className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <div className="flex-1 overflow-auto py-1">
                {isLoading ? (
                  <div className="flex items-center justify-center h-16">
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  <>
                    {!skill.is_builtin && addingFile && (
                      <NewFileDialog
                        onConfirm={createFile}
                        onCancel={() => setAddingFile(false)}
                      />
                    )}
                    {tree.length === 0 && !addingFile && (
                      <div className="px-3 py-6 text-center">
                        <p className="text-xs text-muted-foreground mb-2">No files yet</p>
                        {!skill.is_builtin && (
                          <button
                            onClick={() => createFile("SKILL.md")}
                            className="text-xs text-primary hover:underline"
                          >
                            Create SKILL.md
                          </button>
                        )}
                      </div>
                    )}
                    {tree.map((node) => (
                      <TreeNode
                        key={node.path}
                        node={node}
                        depth={0}
                        selected={selectedPath}
                        onSelect={selectFile}
                        expanded={expanded}
                        onToggle={toggleDir}
                      />
                    ))}
                  </>
                )}
              </div>
            </div>

            {/* Content area */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {selectedPath ? (
                <>
                  {/* File toolbar */}
                  <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
                    <div className="flex items-center gap-2">
                      <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                      <span className="text-xs font-mono text-foreground">{selectedPath}</span>
                      {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="Unsaved changes" />}
                    </div>
                    <div className="flex items-center gap-1">
                      {isMarkdown(selectedPath) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setPreviewMode(!previewMode)}
                          className="h-7 gap-1.5 text-xs"
                        >
                          {previewMode ? <Pencil className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                          {previewMode ? "Edit" : "Preview"}
                        </Button>
                      )}
                      {!skill.is_builtin && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              if (confirm(`Delete ${selectedPath}?`)) deleteFile.mutate(selectedPath);
                            }}
                            className="h-7 text-xs text-destructive hover:text-destructive"
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                          <Button
                            size="sm"
                            onClick={handleSave}
                            disabled={!isDirty || saveFile.isPending}
                            className="h-7 gap-1.5 text-xs"
                          >
                            {saveFile.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                            Save
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Editor / Preview */}
                  <div className="flex-1 overflow-auto">
                    {isMarkdown(selectedPath) && (previewMode || skill.is_builtin) ? (
                      <div className="px-6 py-5 prose prose-sm prose-invert max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                          {editContent || "*Empty file*"}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <textarea
                        value={editContent}
                        readOnly={skill.is_builtin}
                        onChange={(e) => {
                          if (!skill.is_builtin) { setEditContent(e.target.value); setIsDirty(true); }
                        }}
                        onKeyDown={(e) => {
                          if (!skill.is_builtin) {
                            if (e.key === "Tab") {
                              e.preventDefault();
                              const start = e.currentTarget.selectionStart;
                              const end = e.currentTarget.selectionEnd;
                              const newVal = editContent.substring(0, start) + "  " + editContent.substring(end);
                              setEditContent(newVal);
                              setIsDirty(true);
                              requestAnimationFrame(() => {
                                e.currentTarget.selectionStart = e.currentTarget.selectionEnd = start + 2;
                              });
                            }
                            if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                              e.preventDefault();
                              handleSave();
                            }
                          }
                        }}
                        spellCheck={false}
                        className={cn(
                          "w-full h-full resize-none bg-transparent font-mono text-sm px-5 py-4 focus:outline-none leading-relaxed text-foreground",
                          skill.is_builtin && "cursor-default"
                        )}
                        placeholder="Start typing…"
                      />
                    )}
                  </div>
                </>
              ) : (
                <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
                  <FileText className="w-8 h-8 opacity-20" />
                  <p className="text-sm">Select a file to view{!skill.is_builtin && " or edit"}</p>
                  {!skill.is_builtin && Object.keys(files).length === 0 && (
                    <Button size="sm" variant="outline" onClick={() => createFile("SKILL.md")}>
                      <Plus className="w-3.5 h-3.5 mr-1.5" />
                      Create SKILL.md
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
