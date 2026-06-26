"use client";

import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { FolderGit2, Trash2, Loader2, RefreshCw, GitBranch } from "lucide-react";
import toast from "react-hot-toast";

import { workspacesApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui/button";

interface Workspace {
  name: string;
  kind: "project" | "chat" | "other";
  key: string;
  path: string;
  size_bytes: number;
  file_count: number;
  is_git: boolean;
  mtime: number;
}

function fmtSize(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export default function WorkspacesTab() {
  const isSuperuser = useAuthStore((s) => s.user?.is_superuser);
  const qc = useQueryClient();
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const { data: workspaces = [], isLoading, refetch, isFetching } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: () => workspacesApi.list().then((r) => r.data),
    enabled: !!isSuperuser,
  });

  const del = useMutation({
    mutationFn: (name: string) => workspacesApi.remove(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace deleted");
      setPendingDelete(null);
    },
    onError: () => toast.error("Failed to delete workspace"),
  });

  if (!isSuperuser) {
    return <p className="text-xs text-muted-foreground">Agent workspaces are restricted to superusers.</p>;
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <FolderGit2 className="w-4 h-4" /> Agent workspaces
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Persistent directories where agent teams build code. One per project (or per conversation).
            Enable with <code>SHARED_WORKSPACE_ENABLED</code>.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-10 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /></div>
      ) : workspaces.length === 0 ? (
        <p className="text-xs text-muted-foreground py-6 text-center border border-dashed border-border rounded-lg">
          No workspaces yet. They are created the first time an agent uses a file/shell tool with the feature enabled.
        </p>
      ) : (
        <div className="space-y-1.5">
          {workspaces.map((w) => (
            <div key={w.name} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-xs">
              <span className={`px-1.5 py-0.5 rounded uppercase text-[10px] ${w.kind === "project" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>{w.kind}</span>
              <span className="font-mono text-foreground truncate flex-1" title={w.path}>{w.name}</span>
              {w.is_git && <GitBranch className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
              <span className="text-muted-foreground shrink-0">{w.file_count} files</span>
              <span className="text-muted-foreground shrink-0 w-16 text-right">{fmtSize(w.size_bytes)}</span>
              {pendingDelete === w.name ? (
                <span className="flex items-center gap-1 shrink-0">
                  <button onClick={() => del.mutate(w.name)} disabled={del.isPending}
                    className="text-red-400 hover:text-red-300">{del.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Confirm"}</button>
                  <button onClick={() => setPendingDelete(null)} className="text-muted-foreground hover:text-foreground">Cancel</button>
                </span>
              ) : (
                <button onClick={() => setPendingDelete(w.name)} title="Delete workspace"
                  className="text-muted-foreground hover:text-red-400 shrink-0"><Trash2 className="w-3.5 h-3.5" /></button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
