"use client";

import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  XCircle,
  RefreshCw,
  GitMerge,
  Trash2,
  Code2,
  Diff,
  Eye,
  File,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { gitProxyApi } from "@/lib/api";
import toast from "react-hot-toast";
import { buildTree } from "@/lib/file-tree";
import type { TreeItem, CommitEntry } from "@/lib/file-tree";
import { DiffRenderer } from "@/components/chat/DiffRenderer";
import { CodeViewer } from "@/components/chat/CodeViewer";
import { FileTreeNode } from "@/components/chat/FileTreeNode";
import { CommitTimeline } from "@/components/chat/CommitTimeline";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ProjectForExplorer {
  id: string;
  name: string;
  repo_url: string | null;
  repo_type: string | null;
  repo_branch: string | null;
  repo_credential_id: string | null;
}

export interface FileExplorerPanelProps {
  project: ProjectForExplorer;
  onClose: () => void;
}

interface CompareFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  patch: string;
}

// ── Main component ────────────────────────────────────────────────────────────

const PANEL_WIDTH_KEY = "file-explorer-panel-width";
const PANEL_MIN_WIDTH = 280;
const PANEL_MAX_WIDTH = 960;
const PANEL_DEFAULT_WIDTH = 560;

export function FileExplorerPanel({ project, onClose }: FileExplorerPanelProps) {
  const qc = useQueryClient();
  const credId = project.repo_credential_id!;
  const repoUrl = project.repo_url!;
  const defaultBranch = project.repo_branch || "main";

  const [panelWidth, setPanelWidth] = useState<number>(() => {
    if (typeof window === "undefined") return PANEL_DEFAULT_WIDTH;
    const saved = localStorage.getItem(PANEL_WIDTH_KEY);
    if (saved) {
      const n = parseInt(saved, 10);
      if (!isNaN(n)) return Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, n));
    }
    return PANEL_DEFAULT_WIDTH;
  });

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = panelWidth;

    function onMouseMove(ev: MouseEvent) {
      const delta = startX - ev.clientX;
      const next = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, startWidth + delta));
      setPanelWidth(next);
    }

    function onMouseUp(ev: MouseEvent) {
      const delta = startX - ev.clientX;
      const final = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, startWidth + delta));
      localStorage.setItem(PANEL_WIDTH_KEY, String(final));
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [panelWidth]);

  const [activeTab, setActiveTab] = useState<"explorer" | "timeline">("explorer");
  const [selectedAgentBranch, setSelectedAgentBranch] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"code" | "diff">("code");
  const [renderMarkdown, setRenderMarkdown] = useState(true);

  const isMarkdown = useMemo(() => {
    if (!selectedFile) return false;
    const ext = selectedFile.split(".").pop()?.toLowerCase() ?? "";
    return ext === "md" || ext === "mdx";
  }, [selectedFile]);

  // ── Branches ──────────────────────────────────────────────────────────────

  const { data: branchesData, refetch: refetchBranches, isFetching: branchesLoading } = useQuery({
    queryKey: ["git-branches", credId, repoUrl],
    queryFn: () => gitProxyApi.branches(credId, repoUrl).then((r) => r.data as { name: string }[]),
    staleTime: 30_000,
  });

  const agentBranches = useMemo(
    () => (branchesData ?? []).filter((b) => b.name.startsWith("nexora/")),
    [branchesData],
  );

  const resolvedAgentBranch = selectedAgentBranch ?? (agentBranches.length > 0 ? agentBranches[agentBranches.length - 1].name : null);

  // ── File tree ─────────────────────────────────────────────────────────────

  // Show the tree of the branch being viewed (the selected agent branch when there is
  // one) so the explorer reflects the agent's work — not just the base branch, which is
  // often near-empty (e.g. only a README before the first merge).
  const treeBranch = resolvedAgentBranch ?? defaultBranch;
  const { data: treeData, refetch: refetchTree } = useQuery({
    queryKey: ["git-tree", credId, repoUrl, treeBranch],
    queryFn: () => gitProxyApi.tree(credId, repoUrl, treeBranch).then((r) => r.data as TreeItem[]),
    staleTime: 60_000,
  });

  const treeNodes = useMemo(() => buildTree(treeData ?? []), [treeData]);

  // ── Compare (diff) ────────────────────────────────────────────────────────

  const { data: compareData, refetch: refetchCompare } = useQuery({
    queryKey: ["git-compare", credId, repoUrl, defaultBranch, resolvedAgentBranch],
    queryFn: () =>
      gitProxyApi.compare(credId, repoUrl, defaultBranch, resolvedAgentBranch!).then((r) => r.data as {
        ahead_by: number;
        behind_by: number;
        files: CompareFile[];
      }),
    enabled: !!resolvedAgentBranch,
    staleTime: 30_000,
  });

  const modifiedPaths = useMemo(
    () => new Set((compareData?.files ?? []).map((f) => f.path)),
    [compareData],
  );

  // ── File content ──────────────────────────────────────────────────────────

  const branchForFile = resolvedAgentBranch ?? defaultBranch;
  const { data: fileData, isFetching: fileFetching } = useQuery({
    queryKey: ["git-file", credId, repoUrl, selectedFile, branchForFile],
    queryFn: () =>
      gitProxyApi.file(credId, repoUrl, selectedFile!, branchForFile).then((r) => r.data as { content: string; size: number }),
    enabled: !!selectedFile,
    staleTime: 15_000,
  });

  const filePatch = useMemo(() => {
    if (!selectedFile || !resolvedAgentBranch) return null;
    return compareData?.files.find((f) => f.path === selectedFile)?.patch ?? null;
  }, [selectedFile, compareData, resolvedAgentBranch]);

  // ── Commits for timeline ──────────────────────────────────────────────────

  const { data: commitsData } = useQuery({
    queryKey: ["git-commits", credId, repoUrl, resolvedAgentBranch],
    queryFn: () =>
      gitProxyApi.commits(credId, repoUrl, resolvedAgentBranch!).then((r) => r.data as CommitEntry[]),
    enabled: !!resolvedAgentBranch && activeTab === "timeline",
    staleTime: 30_000,
  });

  // ── Handle file selection ─────────────────────────────────────────────────

  function handleSelectFile(path: string) {
    setSelectedFile(path);
    setRenderMarkdown(true);
    const hasDiff = compareData?.files.some((f) => f.path === path);
    if (hasDiff && resolvedAgentBranch) {
      setViewMode("diff");
    } else {
      setViewMode("code");
    }
  }

  // ── Accept (merge) ────────────────────────────────────────────────────────

  const mergeMut = useMutation({
    mutationFn: () =>
      gitProxyApi.merge({
        credential_id: credId,
        repo_url: repoUrl,
        base: defaultBranch,
        head: resolvedAgentBranch!,
        message: `Merge ${resolvedAgentBranch} into ${defaultBranch} via Nexora`,
      }).then((r) => r.data),
    onSuccess: (data) => {
      if (data.merged) {
        toast.success("Branch merged successfully");
      } else {
        toast.success(`MR created: ${data.mr_url}`);
      }
      setSelectedAgentBranch(null);
      qc.invalidateQueries({ queryKey: ["git-branches", credId, repoUrl] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Merge failed";
      toast.error(msg);
    },
  });

  // ── Reject (delete branch) ────────────────────────────────────────────────

  const deleteMut = useMutation({
    mutationFn: () =>
      gitProxyApi.deleteBranch(credId, repoUrl, resolvedAgentBranch!).then((r) => r.data),
    onSuccess: () => {
      toast.success("Branch deleted");
      setSelectedAgentBranch(null);
      setSelectedFile(null);
      qc.invalidateQueries({ queryKey: ["git-branches", credId, repoUrl] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Delete failed";
      toast.error(msg);
    },
  });

  function handleReject() {
    if (!resolvedAgentBranch) return;
    if (!window.confirm(`Delete branch "${resolvedAgentBranch}"? This cannot be undone.`)) return;
    deleteMut.mutate();
  }

  function handleRefresh() {
    refetchBranches();
    refetchTree();
    if (resolvedAgentBranch) refetchCompare();
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className="relative flex flex-col h-full border-l border-border bg-card shrink-0"
      style={{ width: panelWidth }}
    >
      {/* Drag handle */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-20"
        onMouseDown={handleDragStart}
      />
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border shrink-0">
        <span className="text-xs font-semibold truncate flex-1">{project.name}</span>

        {agentBranches.length > 0 && (
          <select
            className="text-[10px] bg-accent border border-border rounded px-1.5 py-0.5 text-muted-foreground max-w-[160px] truncate"
            value={resolvedAgentBranch ?? ""}
            onChange={(e) => setSelectedAgentBranch(e.target.value || null)}
          >
            {agentBranches.map((b) => (
              <option key={b.name} value={b.name}>{b.name.replace("nexora/", "")}</option>
            ))}
          </select>
        )}

        <button
          onClick={handleRefresh}
          disabled={branchesLoading}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          title="Refresh"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", branchesLoading && "animate-spin")} />
        </button>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <XCircle className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border shrink-0">
        <button
          className={cn(
            "px-3 py-1.5 text-xs font-medium transition-colors",
            activeTab === "explorer"
              ? "text-foreground border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setActiveTab("explorer")}
        >
          Explorer
        </button>
        <button
          className={cn(
            "px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1",
            activeTab === "timeline"
              ? "text-foreground border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setActiveTab("timeline")}
        >
          Timeline
          {commitsData && commitsData.length > 0 && (
            <span className="text-[10px] bg-accent px-1 rounded text-muted-foreground">{commitsData.length}</span>
          )}
        </button>
      </div>

      {/* Body */}
      {activeTab === "timeline" ? (
        <CommitTimeline commits={commitsData ?? []} />
      ) : (
        <div className="flex flex-1 min-h-0">
          {/* Left: file tree */}
          <div className="flex flex-col w-44 border-r border-border shrink-0 min-h-0">
            {compareData && compareData.files.length > 0 && (
              <div className="px-2 py-1 border-b border-border shrink-0">
                <span className="text-[10px] text-orange-400">
                  {compareData.files.length} changed
                  {compareData.ahead_by > 0 && ` · +${compareData.ahead_by} commits`}
                </span>
              </div>
            )}

            <div className="flex-1 overflow-y-auto py-1">
              {treeNodes.map((node) => (
                <FileTreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  selectedPath={selectedFile}
                  modifiedPaths={modifiedPaths}
                  onSelectFile={handleSelectFile}
                  defaultOpen={node.type === "dir" && node.path.split("/").length === 1}
                />
              ))}

              {!treeData && compareData && compareData.files.length > 0 && (
                <div className="px-2 py-1 text-[10px] text-muted-foreground">
                  {compareData.files.map((f) => (
                    <button
                      key={f.path}
                      onClick={() => handleSelectFile(f.path)}
                      className={cn(
                        "flex items-center gap-1 w-full py-0.5 text-left hover:text-foreground",
                        selectedFile === f.path && "text-foreground",
                      )}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />
                      <span className="truncate">{f.path}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {resolvedAgentBranch && (
              <div className="border-t border-border p-2 flex flex-col gap-1.5 shrink-0">
                <button
                  onClick={() => mergeMut.mutate()}
                  disabled={mergeMut.isPending}
                  className="flex items-center justify-center gap-1.5 w-full py-1 rounded text-[11px] font-medium bg-green-600/20 text-green-400 hover:bg-green-600/30 transition-colors disabled:opacity-50"
                >
                  <GitMerge className="w-3 h-3" />
                  Accept
                </button>
                <button
                  onClick={handleReject}
                  disabled={deleteMut.isPending}
                  className="flex items-center justify-center gap-1.5 w-full py-1 rounded text-[11px] font-medium bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors disabled:opacity-50"
                >
                  <Trash2 className="w-3 h-3" />
                  Reject
                </button>
              </div>
            )}
          </div>

          {/* Right: file content */}
          <div className="flex flex-col flex-1 min-w-0 min-h-0">
            {selectedFile ? (
              <>
                {/* File header */}
                <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border shrink-0">
                  <span className="text-[11px] text-muted-foreground truncate flex-1 font-mono">{selectedFile}</span>
                  <div className="flex items-center gap-0.5 shrink-0">
                    {isMarkdown && (
                      <button
                        onClick={() => setRenderMarkdown((r) => !r)}
                        className={cn(
                          "flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] transition-colors",
                          renderMarkdown
                            ? "bg-primary/10 border-primary/30 text-primary"
                            : "border-border text-muted-foreground hover:bg-accent",
                        )}
                      >
                        {renderMarkdown
                          ? <><Eye className="w-3 h-3" /> Rendered</>
                          : <><Code2 className="w-3 h-3" /> Source</>
                        }
                      </button>
                    )}
                    {filePatch && (
                      <>
                        <button
                          onClick={() => setViewMode("code")}
                          className={cn(
                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors",
                            viewMode === "code" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          <Code2 className="w-3 h-3" />
                          Code
                        </button>
                        <button
                          onClick={() => setViewMode("diff")}
                          className={cn(
                            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors",
                            viewMode === "diff" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          <Diff className="w-3 h-3" />
                          Diff
                        </button>
                      </>
                    )}
                  </div>
                  {filePatch && (
                    <div className="flex items-center gap-1 shrink-0">
                      <span className="text-[10px] text-green-400">
                        +{compareData?.files.find((f) => f.path === selectedFile)?.additions ?? 0}
                      </span>
                      <span className="text-[10px] text-red-400">
                        -{compareData?.files.find((f) => f.path === selectedFile)?.deletions ?? 0}
                      </span>
                    </div>
                  )}
                </div>

                {/* Content area */}
                <div className="flex-1 overflow-auto">
                  {fileFetching ? (
                    <div className="flex items-center justify-center h-full">
                      <RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" />
                    </div>
                  ) : viewMode === "diff" && filePatch ? (
                    <DiffRenderer patch={filePatch} />
                  ) : fileData && isMarkdown && renderMarkdown ? (
                    <div className="p-5 text-sm leading-relaxed overflow-auto [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mb-3 [&_h1]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mb-1 [&_h3]:mt-3 [&_p]:mb-3 [&_p]:text-muted-foreground [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_code]:font-mono [&_code]:text-xs [&_code]:bg-accent [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_pre]:bg-neutral-950 [&_pre]:rounded-lg [&_pre]:p-4 [&_pre]:overflow-auto [&_pre]:mb-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_blockquote]:italic [&_blockquote]:mb-3 [&_hr]:border-border [&_hr]:my-4 [&_a]:text-primary [&_a]:underline [&_table]:w-full [&_table]:text-xs [&_th]:text-left [&_th]:font-semibold [&_th]:border-b [&_th]:border-border [&_th]:pb-1 [&_th]:px-2 [&_td]:border-b [&_td]:border-border/40 [&_td]:py-1.5 [&_td]:px-2">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{fileData.content}</ReactMarkdown>
                    </div>
                  ) : fileData ? (
                    <CodeViewer content={fileData.content} filename={selectedFile ?? ""} />
                  ) : (
                    <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
                      Failed to load file
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 overflow-y-auto">
                {compareData && compareData.files.length > 0 ? (
                  <div className="py-2">
                    <p className="px-3 text-[10px] text-muted-foreground mb-2 uppercase tracking-wide font-medium">
                      Changed files
                    </p>
                    {compareData.files.map((f) => (
                      <button
                        key={f.path}
                        onClick={() => handleSelectFile(f.path)}
                        className="flex items-center gap-2 w-full px-3 py-1.5 text-xs hover:bg-accent/30 transition-colors text-left"
                      >
                        <span
                          className={cn(
                            "text-[10px] font-mono px-1 rounded shrink-0",
                            f.status === "added" && "bg-green-500/20 text-green-400",
                            f.status === "removed" && "bg-red-500/20 text-red-400",
                            f.status === "modified" && "bg-orange-500/20 text-orange-400",
                            f.status === "renamed" && "bg-blue-500/20 text-blue-400",
                          )}
                        >
                          {(f.status?.[0] ?? "?").toUpperCase()}
                        </span>
                        <span className="font-mono truncate flex-1">{f.path}</span>
                        <span className="text-[10px] text-green-400 shrink-0">+{f.additions}</span>
                        <span className="text-[10px] text-red-400 shrink-0">-{f.deletions}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
                    <File className="w-6 h-6 text-muted-foreground/40" />
                    <p className="text-xs text-muted-foreground">Select a file to view its content</p>
                    {!resolvedAgentBranch && (
                      <p className="text-[11px] text-muted-foreground/60">
                        No agent branches found. Agent branches start with <code>nexora/</code>.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
