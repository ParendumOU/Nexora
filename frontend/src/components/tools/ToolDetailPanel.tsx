"use client";
import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toolsApi } from "@/lib/api";

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
  Save, Loader2, FilePlus, Eye, Pencil, Copy, Check, Download,
  Globe, Monitor, FolderArchive, GitBranch, Github,
  Triangle, Code2, Container, Sparkles, Wrench,
} from "lucide-react";
import { cn, copyToClipboard } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import toast from "react-hot-toast";

interface Tool {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  is_builtin?: boolean;
  env_vars?: string[];
  files?: Record<string, string>;
}

// ─── Category config ──────────────────────────────────────────────────────────

const CAT_ICONS: Record<string, React.ElementType> = {
  web: Globe, browser: Monitor, file: FolderArchive, git: GitBranch,
  github: Github, gitlab: Triangle, code: Code2, docker: Container,
  api: Globe, data: Code2, integration: Sparkles, ai: Sparkles, custom: Wrench,
};

const CAT_COLORS: Record<string, string> = {
  web:         "bg-blue-500/10 text-blue-400 border-blue-500/20",
  browser:     "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  file:        "bg-amber-500/10 text-amber-400 border-amber-500/20",
  git:         "bg-green-500/10 text-green-400 border-green-500/20",
  github:      "bg-purple-500/10 text-purple-400 border-purple-500/20",
  gitlab:      "bg-orange-500/10 text-orange-400 border-orange-500/20",
  code:        "bg-violet-500/10 text-violet-400 border-violet-500/20",
  docker:      "bg-sky-500/10 text-sky-400 border-sky-500/20",
  api:         "bg-blue-500/10 text-blue-400 border-blue-500/20",
  data:        "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  integration: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  ai:          "bg-pink-500/10 text-pink-400 border-pink-500/20",
  custom:      "bg-muted text-muted-foreground border-border",
};

// ─── File tree ────────────────────────────────────────────────────────────────

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: FileNode[];
}

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
  for (const path of Object.keys(files).sort()) {
    const parts = path.split("/");
    const parent = getOrCreateDir(parts, parts.length - 1);
    parent.push({ name: parts[parts.length - 1], path, isDir: false });
  }
  return root;
}

function sortTree(nodes: FileNode[]): FileNode[] {
  return nodes
    .sort((a, b) => (a.isDir !== b.isDir ? (a.isDir ? -1 : 1) : a.name.localeCompare(b.name)))
    .map((n) => ({ ...n, children: n.children ? sortTree(n.children) : undefined }));
}

function TreeNode({
  node, depth, selected, onSelect, expanded, onToggle,
}: {
  node: FileNode; depth: number; selected: string | null;
  onSelect: (p: string) => void; expanded: Set<string>; onToggle: (p: string) => void;
}) {
  const isExpanded = expanded.has(node.path);
  return (
    <div>
      <button
        onClick={() => node.isDir ? onToggle(node.path) : onSelect(node.path)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs rounded transition-colors",
          !node.isDir && selected === node.path ? "bg-primary/10 text-primary font-medium" : "hover:bg-accent/50 text-foreground"
        )}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {node.isDir ? (
          <>{isExpanded ? <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 shrink-0 text-muted-foreground" />}<Folder className="w-3.5 h-3.5 shrink-0 text-amber-400" /></>
        ) : (
          <><span className="w-3 shrink-0" /><FileText className="w-3.5 h-3.5 shrink-0 text-blue-400" /></>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {node.isDir && isExpanded && node.children && (
        <div>{node.children.map((c) => <TreeNode key={c.path} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} expanded={expanded} onToggle={onToggle} />)}</div>
      )}
    </div>
  );
}

function isMarkdown(path: string) { return path.endsWith(".md") || path.endsWith(".mdx"); }

function NewFileDialog({ onConfirm, onCancel }: { onConfirm: (p: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
      <Input
        autoFocus value={value} onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) onConfirm(value.trim()); if (e.key === "Escape") onCancel(); }}
        placeholder="path/to/file.md" className="h-6 text-xs font-mono py-0 px-1"
      />
      <button onClick={() => value.trim() && onConfirm(value.trim())} className="text-primary hover:text-primary/80"><ChevronRight className="w-3.5 h-3.5" /></button>
      <button onClick={onCancel} className="text-muted-foreground hover:text-foreground"><X className="w-3 h-3" /></button>
    </div>
  );
}

// ─── Env var card ─────────────────────────────────────────────────────────────

function EnvVarCard({ name }: { name: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    copyToClipboard(name);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20">
      <code className="text-xs font-mono text-amber-400">{name}</code>
      <button onClick={copy} className="text-muted-foreground hover:text-foreground transition-colors">
        {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

const DEFAULT_TOOL_MD = `# Tool: {name}

## Description
Describe what this tool does.

## Parameters
- \`param1\`: Description of param1

## Examples
\`\`\`
Example usage here
\`\`\`
`;

export function ToolDetailPanel({ tool, onClose }: { tool: Tool; onClose: () => void }) {
  const qc = useQueryClient();
  const CatIcon = CAT_ICONS[tool.category] ?? Wrench;
  const isBuiltin = !!tool.is_builtin || tool.id.startsWith("builtin:");
  const envVars = tool.env_vars ?? [];

  // ── File state ──────────────────────────────────────────────────
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const [previewMode, setPreviewMode] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [addingFile, setAddingFile] = useState(false);

  // Builtin tools fetch from /tools/builtin/{key}/files; custom from /tools/{id}/files
  const { data: fileTree, isLoading } = useQuery<{ files: Record<string, string> }>({
    queryKey: isBuiltin ? ["tool-builtin-files", tool.key] : ["tool-files", tool.id],
    queryFn: () =>
      isBuiltin
        ? toolsApi.builtinFiles(tool.key).then((r) => r.data)
        : toolsApi.files(tool.id).then((r) => r.data),
  });

  // Merge inline files (builtins have them in the response) with fetched files
  const rawFiles = fileTree?.files ?? tool.files ?? {};
  const files = isBuiltin
    ? Object.fromEntries(Object.entries(rawFiles).filter(([k]) => k !== "tool.json"))
    : rawFiles;
  const tree = sortTree(buildTree(files));

  useEffect(() => {
    if (!selectedPath) {
      const keys = Object.keys(files);
      const pref = keys.find((k) => k === "TOOL.md") ?? keys[0];
      if (pref) {
        setSelectedPath(pref);
        setEditContent(files[pref]);
        setPreviewMode(isMarkdown(pref));
      }
    }
  }, [files, selectedPath]);

  const selectFile = useCallback((path: string) => {
    if (isDirty && !confirm("Discard unsaved changes?")) return;
    setSelectedPath(path);
    setEditContent(files[path] ?? "");
    setPreviewMode(isMarkdown(path));
    setIsDirty(false);
  }, [files, isDirty]);

  const toggleDir = (path: string) =>
    setExpanded((s) => { const n = new Set(s); n.has(path) ? n.delete(path) : n.add(path); return n; });

  const saveFile = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      toolsApi.putFile(tool.id, path, content),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tool-files", tool.id] }); setIsDirty(false); toast.success("Saved"); },
    onError: () => toast.error("Failed to save"),
  });

  const deleteFileMut = useMutation({
    mutationFn: (path: string) => toolsApi.deleteFile(tool.id, path),
    onSuccess: (_, path) => {
      qc.invalidateQueries({ queryKey: ["tool-files", tool.id] });
      if (selectedPath === path) { setSelectedPath(null); setEditContent(""); }
      toast.success("File deleted");
    },
    onError: () => toast.error("Failed to delete"),
  });

  const createFile = async (path: string) => {
    const defaultContent = path === "TOOL.md"
      ? DEFAULT_TOOL_MD.replace("{name}", tool.name)
      : path.endsWith(".md") ? `# ${path.split("/").pop()?.replace(".md", "")}\n\n` : "";
    await toolsApi.putFile(tool.id, path, defaultContent);
    qc.invalidateQueries({ queryKey: ["tool-files", tool.id] });
    setSelectedPath(path); setEditContent(defaultContent);
    setPreviewMode(isMarkdown(path)); setIsDirty(false); setAddingFile(false);
    toast.success("File created");
  };

  const handleSave = () => selectedPath && saveFile.mutate({ path: selectedPath, content: editContent });

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex flex-col bg-background border-l border-border w-full max-w-4xl h-full shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-start gap-3">
            <div className={cn("w-9 h-9 rounded-xl border flex items-center justify-center shrink-0 mt-0.5", CAT_COLORS[tool.category] ?? CAT_COLORS.custom)}>
              <CatIcon className="w-4.5 h-4.5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-semibold">{tool.name}</h2>
                <code className="text-xs text-muted-foreground font-mono">{tool.key}</code>
                <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", CAT_COLORS[tool.category] ?? CAT_COLORS.custom)}>
                  {tool.category}
                </Badge>
                {isBuiltin && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>}
              </div>
              {tool.description && <p className="text-xs text-muted-foreground mt-0.5 max-w-lg">{tool.description}</p>}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <Button
              size="sm" variant="ghost"
              className="h-7 gap-1.5 text-xs"
              onClick={async () => {
                try {
                  const res = isBuiltin
                    ? await toolsApi.builtinExport(tool.key)
                    : await toolsApi.export(tool.id);
                  downloadBlob(res.data as Blob, `tool_${tool.key}.zip`);
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

        {/* ── Body ── */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left: sidebar */}
          <div className="w-56 border-r border-border flex flex-col shrink-0">
            {/* Env vars */}
            {envVars.length > 0 && (
              <div className="px-3 py-3 border-b border-border">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">Required env vars</p>
                <div className="space-y-1.5">
                  {envVars.map((v) => <EnvVarCard key={v} name={v} />)}
                </div>
              </div>
            )}

            {/* File tree */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Files</span>
              {!isBuiltin && (
                <button onClick={() => setAddingFile(true)} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="New file">
                  <FilePlus className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <div className="flex-1 overflow-auto py-1">
              {isLoading ? (
                <div className="flex items-center justify-center h-16"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>
              ) : (
                <>
                  {!isBuiltin && addingFile && <NewFileDialog onConfirm={createFile} onCancel={() => setAddingFile(false)} />}
                  {tree.length === 0 && !addingFile && (
                    <div className="px-3 py-6 text-center">
                      <p className="text-xs text-muted-foreground mb-2">No files yet</p>
                      {!isBuiltin && <button onClick={() => createFile("TOOL.md")} className="text-xs text-primary hover:underline">Create TOOL.md</button>}
                    </div>
                  )}
                  {tree.map((node) => (
                    <TreeNode key={node.path} node={node} depth={0} selected={selectedPath} onSelect={selectFile} expanded={expanded} onToggle={toggleDir} />
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Right: content area */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {selectedPath ? (
              <>
                {/* File toolbar */}
                <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
                  <div className="flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono text-foreground">{selectedPath}</span>
                    {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="Unsaved" />}
                  </div>
                  <div className="flex items-center gap-1">
                    {isMarkdown(selectedPath) && (
                      <Button size="sm" variant="ghost" onClick={() => setPreviewMode(!previewMode)} className="h-7 gap-1.5 text-xs">
                        {previewMode ? <Pencil className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                        {previewMode ? "Edit" : "Preview"}
                      </Button>
                    )}
                    {!isBuiltin && (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => { if (confirm(`Delete ${selectedPath}?`)) deleteFileMut.mutate(selectedPath); }} className="h-7 text-xs text-destructive hover:text-destructive">
                          <Trash2 className="w-3 h-3" />
                        </Button>
                        <Button size="sm" onClick={handleSave} disabled={!isDirty || saveFile.isPending} className="h-7 gap-1.5 text-xs">
                          {saveFile.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                          Save
                        </Button>
                      </>
                    )}
                  </div>
                </div>

                {/* Editor / Preview */}
                <div className="flex-1 overflow-auto">
                  {isMarkdown(selectedPath) && (previewMode || isBuiltin) ? (
                    <div className="px-6 py-5 prose prose-sm prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                        {editContent || "*Empty file*"}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <textarea
                      value={editContent}
                      readOnly={isBuiltin}
                      onChange={(e) => { if (!isBuiltin) { setEditContent(e.target.value); setIsDirty(true); } }}
                      onKeyDown={(e) => {
                        if (!isBuiltin) {
                          if (e.key === "Tab") {
                            e.preventDefault();
                            const s = e.currentTarget.selectionStart, end = e.currentTarget.selectionEnd;
                            const v = editContent.substring(0, s) + "  " + editContent.substring(end);
                            setEditContent(v); setIsDirty(true);
                            requestAnimationFrame(() => { e.currentTarget.selectionStart = e.currentTarget.selectionEnd = s + 2; });
                          }
                          if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); handleSave(); }
                        }
                      }}
                      spellCheck={false}
                      className={cn(
                        "w-full h-full resize-none bg-transparent font-mono text-sm px-5 py-4 focus:outline-none leading-relaxed text-foreground",
                        isBuiltin && "cursor-default"
                      )}
                      placeholder="Start typing…"
                    />
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center flex-1 gap-3 text-muted-foreground">
                <FileText className="w-8 h-8 opacity-20" />
                <p className="text-sm">Select a file to view</p>
                {!isBuiltin && Object.keys(files).length === 0 && (
                  <Button size="sm" variant="outline" onClick={() => createFile("TOOL.md")}>
                    <Plus className="w-3.5 h-3.5 mr-1.5" />Create TOOL.md
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
