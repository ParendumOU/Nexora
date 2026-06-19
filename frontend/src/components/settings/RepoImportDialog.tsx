"use client";
import { useState, useCallback } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { gitCredentialsApi, projectsApi } from "@/lib/api";
import toast from "react-hot-toast";
import {
  X, Loader2, Github, GitMerge, ChevronRight, ChevronDown,
  Lock, Globe, FolderOpen, Folder, CheckSquare, Square, MinusSquare,
} from "lucide-react";

type GitCredential = {
  id: string;
  name: string;
  provider: string;
  color: string;
  base_url: string | null;
  token_hint: string;
};

type RepoNode = {
  id: string;
  name: string;
  full_name: string;
  web_url: string;
  description: string;
  is_private: boolean;
  default_branch: string;
};

type GroupNode = {
  id: string;
  type: "user" | "org" | "group" | "subgroup";
  name: string;
  full_path?: string;
  avatar_url?: string;
  repos: RepoNode[];
  subgroups: GroupNode[];
  children_loaded: boolean;
  loading?: boolean;
};

// ── helpers ───────────────────────────────────────────────────────────────────

function groupRepoKey(groupId: string, repoId: string) {
  return `${groupId}::${repoId}`;
}

function collectLoadedRepoIds(nodes: GroupNode[]): string[] {
  const ids: string[] = [];
  const walk = (gs: GroupNode[]) => {
    for (const g of gs) {
      for (const r of g.repos) ids.push(groupRepoKey(g.id, r.id));
      if (g.subgroups?.length) walk(g.subgroups);
    }
  };
  walk(nodes);
  return ids;
}

function collectGroupRepoIds(g: GroupNode): string[] {
  const ids = g.repos.map(r => groupRepoKey(g.id, r.id));
  if (g.subgroups?.length) {
    for (const sg of g.subgroups) ids.push(...collectGroupRepoIds(sg));
  }
  return ids;
}

function updateNodeInTree(
  nodes: GroupNode[],
  id: string,
  updater: (n: GroupNode) => GroupNode,
): GroupNode[] {
  return nodes.map(n => {
    if (n.id === id) return updater(n);
    if (n.subgroups?.length) return { ...n, subgroups: updateNodeInTree(n.subgroups, id, updater) };
    return n;
  });
}

function buildRepoMap(nodes: GroupNode[]): Map<string, { repo: RepoNode; groupId: string }> {
  const map = new Map<string, { repo: RepoNode; groupId: string }>();
  const walk = (gs: GroupNode[]) => {
    for (const g of gs) {
      for (const r of g.repos) map.set(groupRepoKey(g.id, r.id), { repo: r, groupId: g.id });
      if (g.subgroups?.length) walk(g.subgroups);
    }
  };
  walk(nodes);
  return map;
}

// ── RepoRow ───────────────────────────────────────────────────────────────────

function RepoRow({ repo, groupId, selected, onToggle }: {
  repo: RepoNode;
  groupId: string;
  selected: Set<string>;
  onToggle: (k: string) => void;
}) {
  const key = groupRepoKey(groupId, repo.id);
  const checked = selected.has(key);
  return (
    <button
      onClick={() => onToggle(key)}
      className={cn(
        "w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-left transition-colors hover:bg-accent/50",
        checked && "bg-primary/8 hover:bg-primary/12",
      )}
    >
      {checked
        ? <CheckSquare className="w-3.5 h-3.5 shrink-0 text-primary" />
        : <Square className="w-3.5 h-3.5 shrink-0 text-muted-foreground/50" />}
      {repo.is_private
        ? <Lock className="w-3 h-3 shrink-0 text-yellow-500" />
        : <Globe className="w-3 h-3 shrink-0 text-muted-foreground/50" />}
      <span className="text-xs font-medium truncate flex-1">{repo.name}</span>
      {repo.description && (
        <span className="text-xs text-muted-foreground/60 truncate max-w-[180px] hidden sm:block">
          {repo.description}
        </span>
      )}
      <span className="text-[10px] text-muted-foreground/50 font-mono shrink-0">{repo.default_branch}</span>
    </button>
  );
}

// ── GroupNodeView ─────────────────────────────────────────────────────────────

function GroupNodeView({ group, selected, onToggle, onToggleGroup, onExpand, depth = 0 }: {
  group: GroupNode;
  selected: Set<string>;
  onToggle: (k: string) => void;
  onToggleGroup: (g: GroupNode) => void;
  onExpand: (id: string) => void;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const ids = collectGroupRepoIds(group);
  const checkedCount = ids.filter(id => selected.has(id)).length;
  const allChecked = ids.length > 0 && checkedCount === ids.length;
  const someChecked = checkedCount > 0 && !allChecked;

  const handleExpandToggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !group.children_loaded && !group.loading) {
      onExpand(group.id);
    }
  };

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-border pl-2")}>
      <div className="flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-accent/30 transition-colors">
        <button onClick={handleExpandToggle} className="text-muted-foreground shrink-0">
          {group.loading
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : expanded
              ? <ChevronDown className="w-3.5 h-3.5" />
              : <ChevronRight className="w-3.5 h-3.5" />}
        </button>
        <button onClick={() => onToggleGroup(group)} className="shrink-0" disabled={ids.length === 0 && !group.children_loaded}>
          {allChecked
            ? <CheckSquare className="w-3.5 h-3.5 text-primary" />
            : someChecked
              ? <MinusSquare className="w-3.5 h-3.5 text-primary/60" />
              : <Square className="w-3.5 h-3.5 text-muted-foreground/40" />}
        </button>
        {expanded
          ? <FolderOpen className="w-3.5 h-3.5 shrink-0 text-yellow-500/80" />
          : <Folder className="w-3.5 h-3.5 shrink-0 text-yellow-500/60" />}
        <span className="text-xs font-semibold flex-1 truncate">{group.name}</span>
        {group.children_loaded && (
          <span className="text-[10px] text-muted-foreground/60 shrink-0 font-mono">
            {group.repos.length} repo{group.repos.length !== 1 ? "s" : ""}
            {group.subgroups?.length > 0 ? ` · ${group.subgroups.length} subgroup${group.subgroups.length !== 1 ? "s" : ""}` : ""}
          </span>
        )}
      </div>

      {expanded && (
        <div className="ml-6 space-y-0.5 mt-0.5">
          {group.loading && (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground/60">
              <Loader2 className="w-3 h-3 animate-spin" />Loading…
            </div>
          )}
          {group.repos.map(r => (
            <RepoRow key={r.id} repo={r} groupId={group.id} selected={selected} onToggle={onToggle} />
          ))}
          {group.subgroups?.map(sg => (
            <GroupNodeView
              key={sg.id}
              group={sg}
              selected={selected}
              onToggle={onToggle}
              onToggleGroup={onToggleGroup}
              onExpand={onExpand}
              depth={depth + 1}
            />
          ))}
          {group.children_loaded && group.repos.length === 0 && !group.subgroups?.length && (
            <p className="text-xs text-muted-foreground/40 px-2 py-1">No repositories</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── RepoImportDialog ──────────────────────────────────────────────────────────

interface RepoImportDialogProps {
  credential: GitCredential | null;
  onClose: () => void;
}

export default function RepoImportDialog({ credential, onClose }: RepoImportDialogProps) {
  const qc = useQueryClient();
  const [groups, setGroups] = useState<GroupNode[]>([]);
  const [rootLoading, setRootLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);

  const open = !!credential;

  const reset = () => { setGroups([]); setLoaded(false); setSelected(new Set()); };

  const handleOpenChange = (o: boolean) => { if (!o) { onClose(); reset(); } };

  const fetchRoots = async () => {
    if (!credential) return;
    setRootLoading(true);
    reset();
    try {
      const res = await gitCredentialsApi.expand(credential.id);
      setGroups((res.data as { subgroups: GroupNode[] }).subgroups || []);
      setLoaded(true);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? "Failed to fetch groups";
      toast.error(msg);
    } finally {
      setRootLoading(false);
    }
  };

  const handleExpand = useCallback(async (nodeId: string) => {
    if (!credential) return;
    setGroups(prev => updateNodeInTree(prev, nodeId, n => ({ ...n, loading: true })));
    try {
      const res = await gitCredentialsApi.expand(credential.id, nodeId);
      const { repos, subgroups } = res.data as { repos: RepoNode[]; subgroups: GroupNode[] };
      setGroups(prev => updateNodeInTree(prev, nodeId, n => ({
        ...n,
        repos: repos || [],
        subgroups: subgroups || [],
        children_loaded: true,
        loading: false,
      })));
    } catch {
      setGroups(prev => updateNodeInTree(prev, nodeId, n => ({ ...n, loading: false })));
      toast.error("Failed to load repositories for this group");
    }
  }, [credential]);

  const toggleRepo = useCallback((key: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);

  const toggleGroup = useCallback((group: GroupNode) => {
    const ids = collectGroupRepoIds(group);
    if (!ids.length) return;
    setSelected(prev => {
      const next = new Set(prev);
      const allIn = ids.every(id => next.has(id));
      if (allIn) ids.forEach(id => next.delete(id));
      else ids.forEach(id => next.add(id));
      return next;
    });
  }, []);

  const loadedIds = collectLoadedRepoIds(groups);
  const allLoadedChecked = loadedIds.length > 0 && loadedIds.every(id => selected.has(id));

  const handleSelectAllLoaded = () => {
    if (allLoadedChecked) setSelected(new Set());
    else setSelected(new Set(loadedIds));
  };

  const handleImport = async () => {
    if (!credential || selected.size === 0) return;
    setImporting(true);
    const repoMap = buildRepoMap(groups);
    const repos = Array.from(selected)
      .map(key => repoMap.get(key))
      .filter(Boolean)
      .map(entry => ({
        name: entry!.repo.name,
        repo_url: entry!.repo.web_url,
        repo_type: credential.provider,
        credential_id: credential.id,
        description: entry!.repo.description || undefined,
        default_branch: entry!.repo.default_branch,
      }));

    try {
      await projectsApi.bulkImport(repos);
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success(`Imported ${repos.length} project${repos.length !== 1 ? "s" : ""}`);
      onClose();
      reset();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Import failed";
      toast.error(msg);
    } finally {
      setImporting(false);
    }
  };

  const ProviderIcon = credential?.provider === "github" ? Github : GitMerge;

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-2xl max-h-[85vh] bg-card border border-border rounded-2xl shadow-2xl flex flex-col">

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
            <div className="flex items-center gap-2.5">
              <ProviderIcon className="w-4 h-4 text-muted-foreground" />
              <div>
                <Dialog.Title className="text-sm font-semibold">Import Repositories</Dialog.Title>
                {credential && (
                  <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full inline-block" style={{ background: credential.color }} />
                    {credential.name} · {credential.token_hint}
                  </p>
                )}
              </div>
            </div>
            <button onClick={onClose} className="p-1 rounded hover:bg-accent text-muted-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
            {!loaded ? (
              <div className="flex flex-col items-center gap-4 py-12">
                <div className="p-3 rounded-xl bg-accent/40 border border-border">
                  <ProviderIcon className="w-6 h-6 text-muted-foreground" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium">Browse repositories</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Load groups, then expand each to browse repos inside
                  </p>
                </div>
                <Button onClick={fetchRoots} disabled={rootLoading}>
                  {rootLoading
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />Loading…</>
                    : "Load groups"}
                </Button>
              </div>
            ) : groups.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-12 text-center">
                <p className="text-sm font-medium">No groups found</p>
                <p className="text-xs text-muted-foreground">The token may not have access to any groups</p>
                <Button size="sm" variant="outline" onClick={fetchRoots}>Retry</Button>
              </div>
            ) : (
              <div className="space-y-0.5">
                {groups.map(g => (
                  <GroupNodeView
                    key={g.id}
                    group={g}
                    selected={selected}
                    onToggle={toggleRepo}
                    onToggleGroup={toggleGroup}
                    onExpand={handleExpand}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          {loaded && groups.length > 0 && (
            <div className="flex items-center justify-between px-5 py-3.5 border-t border-border shrink-0 bg-accent/20">
              <div className="flex items-center gap-3">
                <button
                  onClick={handleSelectAllLoaded}
                  disabled={loadedIds.length === 0}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
                >
                  {allLoadedChecked
                    ? <CheckSquare className="w-3.5 h-3.5 text-primary" />
                    : <Square className="w-3.5 h-3.5" />}
                  {allLoadedChecked ? "Deselect all" : "Select all loaded"}
                </button>
                {loadedIds.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {selected.size > 0
                      ? `${selected.size} of ${loadedIds.length} selected`
                      : `${loadedIds.length} loaded`}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
                <Button size="sm" onClick={handleImport} disabled={selected.size === 0 || importing}>
                  {importing
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />Importing…</>
                    : `Import ${selected.size > 0 ? selected.size : ""} project${selected.size !== 1 ? "s" : ""}`}
                </Button>
              </div>
            </div>
          )}

        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
