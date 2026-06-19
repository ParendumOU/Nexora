"use client";
import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { mcpServersApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Loader2, Plus, Trash2, Server, Pencil, X, ExternalLink,
  Search, RefreshCw, ChevronDown, ChevronRight, Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";

interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

interface McpServer {
  id: string;
  name: string;
  description: string | null;
  url: string;
  config: Record<string, unknown>;
  auth_type: string;
  known_tools: McpTool[];
}

const AUTH_BADGE: Record<string, string> = {
  none:   "bg-muted text-muted-foreground border-border",
  token:  "bg-amber-500/10 text-amber-400 border-amber-500/20",
  bearer: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  oauth:  "bg-blue-500/10 text-blue-400 border-blue-500/20",
  header: "bg-violet-500/10 text-violet-400 border-violet-500/20",
};

const AUTH_TYPES = ["none", "token", "bearer", "header", "oauth"];

// ─── Add/Edit dialog ──────────────────────────────────────────────────────────

function McpFormDialog({
  open, onClose, initial, mcpId,
}: {
  open: boolean;
  onClose: () => void;
  initial?: McpServer;
  mcpId?: string;
}) {
  const qc = useQueryClient();
  const isEdit = !!mcpId;
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    url: initial?.url ?? "",
    description: initial?.description ?? "",
    auth_type: initial?.auth_type ?? "none",
    auth_value: "",
    config: initial?.config ? JSON.stringify(initial.config, null, 2) : "{}",
  });
  const [loading, setLoading] = useState(false);
  const [configError, setConfigError] = useState("");

  const SELECT_CLS = "w-full h-8 appearance-none text-sm bg-background text-foreground border border-input rounded-md px-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [color-scheme:dark]";

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.url.trim()) { toast.error("Name and URL are required"); return; }
    let config: object = {};
    try { config = JSON.parse(form.config); } catch { setConfigError("Invalid JSON"); return; }
    setConfigError("");
    setLoading(true);
    try {
      const payload = {
        name: form.name, url: form.url,
        description: form.description || undefined,
        auth_type: form.auth_type,
        auth_value: form.auth_value || undefined,
        config,
      };
      if (isEdit) {
        await mcpServersApi.update(mcpId!, payload);
        toast.success("MCP server updated");
      } else {
        await mcpServersApi.create(payload);
        toast.success("MCP server added");
      }
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      onClose();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to save MCP server");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold">{isEdit ? "Edit MCP Server" : "Add MCP Server"}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-4 h-4" /></button>
            </Dialog.Close>
          </div>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="My MCP Server" className="h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">URL</label>
              <Input value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} placeholder="http://localhost:9990" className="h-8 text-sm font-mono" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Description (optional)</label>
              <Input value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} placeholder="What this server provides" className="h-8 text-sm" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Auth type</label>
                <select value={form.auth_type} onChange={(e) => setForm((f) => ({ ...f, auth_type: e.target.value }))} className={SELECT_CLS}>
                  {AUTH_TYPES.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
              {form.auth_type !== "none" && (
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Auth value / token</label>
                  <Input value={form.auth_value} onChange={(e) => setForm((f) => ({ ...f, auth_value: e.target.value }))} placeholder="sk-…" className="h-8 text-sm font-mono" type="password" />
                </div>
              )}
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Config JSON</label>
              <textarea
                value={form.config}
                onChange={(e) => setForm((f) => ({ ...f, config: e.target.value }))}
                className={cn("w-full h-24 text-xs font-mono bg-background border rounded-md px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-ring", configError ? "border-destructive" : "border-input")}
              />
              {configError && <p className="text-xs text-destructive">{configError}</p>}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={handleSubmit} disabled={loading}>
              {loading && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              {isEdit ? "Save Changes" : "Add Server"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Server row ───────────────────────────────────────────────────────────────

function McpServerRow({
  server,
  onEdit,
  onDelete,
}: {
  server: McpServer;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [fetching, setFetching] = useState(false);

  const toolCount = server.known_tools?.length ?? 0;

  const handleFetch = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setFetching(true);
    try {
      await mcpServersApi.fetchTools(server.id);
      qc.invalidateQueries({ queryKey: ["mcp-servers"] });
      toast.success("Tools fetched");
      setExpanded(true);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      toast.error(e.response?.data?.detail || "Could not fetch tools from server");
    } finally {
      setFetching(false);
    }
  };

  return (
    <div className="border-b border-border/60 last:border-0">
      <div
        className="flex items-start gap-4 px-5 py-4 hover:bg-accent/20 transition-colors group cursor-pointer"
        onClick={() => toolCount > 0 && setExpanded((x) => !x)}
      >
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
          <Server className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className="text-sm font-medium">{server.name}</span>
            <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", AUTH_BADGE[server.auth_type] ?? AUTH_BADGE.none)}>
              {server.auth_type}
            </Badge>
            {toolCount > 0 && (
              <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                <Wrench className="w-3 h-3" />
                {toolCount} tool{toolCount !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          {server.description && <p className="text-xs text-muted-foreground mb-1">{server.description}</p>}
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <ExternalLink className="w-3 h-3 shrink-0" />
            <span className="font-mono truncate">{server.url}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={handleFetch}
            disabled={fetching}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-all"
            title="Fetch tools from server"
          >
            {fetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-all"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-destructive transition-all"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          {toolCount > 0 && (
            <span className="text-muted-foreground/40 ml-1">
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </span>
          )}
        </div>
      </div>

      {/* Tool list */}
      {expanded && toolCount > 0 && (
        <div className="px-5 pb-3 ml-12">
          <div className="border border-border rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-accent/30 border-b border-border">
                  <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Tool</th>
                  <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {server.known_tools.map((tool) => (
                  <tr key={tool.name} className="hover:bg-accent/10">
                    <td className="px-3 py-2 font-mono font-medium text-foreground whitespace-nowrap">{tool.name}</td>
                    <td className="px-3 py-2 text-muted-foreground max-w-sm">
                      <span className="line-clamp-2">{tool.description || "—"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function McpsPage() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<McpServer | null>(null);
  const [search, setSearch] = useState("");

  const { data: servers = [], isLoading } = useQuery<McpServer[]>({
    queryKey: ["mcp-servers"],
    queryFn: () => mcpServersApi.list().then((r) => r.data),
  });

  const del = useMutation({
    mutationFn: (id: string) => mcpServersApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mcp-servers"] }); toast.success("MCP server removed"); },
    onError: () => toast.error("Failed to delete MCP server"),
  });

  const filtered = useMemo(() =>
    servers.filter((s) =>
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description ?? "").toLowerCase().includes(search.toLowerCase()) ||
      s.url.toLowerCase().includes(search.toLowerCase())
    ), [servers, search]);

  const totalTools = servers.reduce((acc, s) => acc + (s.known_tools?.length ?? 0), 0);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold">MCP Servers</h1>
          <p className="text-sm text-muted-foreground">
            {servers.length} server{servers.length !== 1 ? "s" : ""} · {totalTools} tool{totalTools !== 1 ? "s" : ""} discovered
          </p>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
          <Plus className="w-3.5 h-3.5" />
          Add Server
        </Button>
      </div>

      {/* Search */}
      <div className="px-6 py-2.5 border-b border-border shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search servers by name, description, or URL…"
            className="pl-8 h-8 text-sm"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60 text-muted-foreground gap-3">
            <Server className="w-10 h-10 opacity-20" />
            <p className="text-sm">{search ? "No servers match your search" : "No MCP servers configured yet"}</p>
            {!search && (
              <Button size="sm" variant="outline" onClick={() => setAddOpen(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Add your first server
              </Button>
            )}
          </div>
        ) : (
          <div>
            <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                {search ? `${filtered.length} of ${servers.length} servers` : `${servers.length} server${servers.length !== 1 ? "s" : ""}`}
              </span>
              <span className="text-[10px] text-muted-foreground ml-auto">Hover a row and click ↻ to discover tools</span>
            </div>
            {filtered.map((server) => (
              <McpServerRow
                key={server.id}
                server={server}
                onEdit={() => setEditTarget(server)}
                onDelete={() => del.mutate(server.id)}
              />
            ))}
          </div>
        )}
      </div>

      <McpFormDialog open={addOpen} onClose={() => setAddOpen(false)} />
      {editTarget && (
        <McpFormDialog
          open={!!editTarget}
          onClose={() => setEditTarget(null)}
          initial={editTarget}
          mcpId={editTarget.id}
        />
      )}
    </div>
  );
}
