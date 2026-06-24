"use client";
import { useState, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toolsApi, seedsApi, type ToolEnvStatus } from "@/lib/api";
import { ToolEnvModal } from "@/components/tools/ToolEnvModal";
import { EnvVarModal, type RequiredEnvVar } from "@/components/tools/EnvVarModal";
import { RiskAckDialog } from "@/components/marketplace/RiskAckDialog";
import { useMarketplaceImport } from "@/components/marketplace/useMarketplaceImport";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Loader2, Plus, Trash2, Wrench, X, ChevronRight,
  Globe, Monitor, FolderArchive, GitBranch, Github,
  Triangle, Code2, Container, Search, Sparkles, Upload, Link,
  Radio, Layers, Brain, CircleDot, Server, Workflow, FolderKanban,
} from "lucide-react";
import { cn, copyToClipboard } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import { ToolDetailPanel } from "@/components/tools/ToolDetailPanel";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Tool {
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

const CATEGORIES: Record<string, {
  label: string;
  Icon: React.ElementType;
  color: string;
  badge: string;
  desc: string;
}> = {
  web:         { label: "Web & HTTP",       Icon: Globe,        color: "text-blue-400",    badge: "bg-blue-500/10 text-blue-400 border-blue-500/20",    desc: "HTTP client, scraping, search" },
  browser:     { label: "Browser",          Icon: Monitor,      color: "text-cyan-400",    badge: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",    desc: "Playwright automation" },
  file:        { label: "Files & Archive",  Icon: FolderArchive,color: "text-amber-400",   badge: "bg-amber-500/10 text-amber-400 border-amber-500/20", desc: "Read, write, zip, find" },
  git:         { label: "Git",              Icon: GitBranch,    color: "text-green-400",   badge: "bg-green-500/10 text-green-400 border-green-500/20", desc: "Clone, commit, push, diff" },
  github:      { label: "GitHub",           Icon: Github,       color: "text-purple-400",  badge: "bg-purple-500/10 text-purple-400 border-purple-500/20", desc: "Issues, PRs, commits via API" },
  gitlab:      { label: "GitLab",           Icon: Triangle,     color: "text-orange-400",  badge: "bg-orange-500/10 text-orange-400 border-orange-500/20", desc: "Issues, MRs, pipelines via API" },
  code:        { label: "Code & Shell",     Icon: Code2,        color: "text-violet-400",  badge: "bg-violet-500/10 text-violet-400 border-violet-500/20", desc: "Python, Node.js, shell, format" },
  docker:      { label: "Docker",           Icon: Container,    color: "text-sky-400",     badge: "bg-sky-500/10 text-sky-400 border-sky-500/20",       desc: "Containers, images, logs" },
  api:         { label: "API",              Icon: Globe,        color: "text-blue-400",    badge: "bg-blue-500/10 text-blue-400 border-blue-500/20",    desc: "API integrations" },
  data:        { label: "Data",             Icon: Code2,        color: "text-emerald-400", badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", desc: "Data processing" },
  integration: { label: "Integration",      Icon: Sparkles,     color: "text-orange-400",  badge: "bg-orange-500/10 text-orange-400 border-orange-500/20", desc: "Third-party integrations" },
  ai:          { label: "AI",               Icon: Sparkles,     color: "text-pink-400",    badge: "bg-pink-500/10 text-pink-400 border-pink-500/20",    desc: "AI-powered utilities" },
  agent_bus:   { label: "Agent Bus",        Icon: Radio,        color: "text-teal-400",    badge: "bg-teal-500/10 text-teal-400 border-teal-500/20",    desc: "Agent-to-agent messaging" },
  platform:    { label: "Platform",         Icon: Layers,       color: "text-indigo-400",  badge: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20", desc: "Platform resource management" },
  memory:      { label: "Memory",           Icon: Brain,        color: "text-rose-400",    badge: "bg-rose-500/10 text-rose-400 border-rose-500/20",    desc: "Semantic memory & knowledge" },
  issues:      { label: "Issues",           Icon: CircleDot,    color: "text-yellow-400",  badge: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20", desc: "Issue tracking" },
  infrastructure: { label: "Infrastructure",Icon: Server,       color: "text-slate-400",   badge: "bg-slate-500/10 text-slate-400 border-slate-500/20", desc: "Infrastructure & deployment" },
  feature:     { label: "Features",         Icon: Sparkles,     color: "text-fuchsia-400", badge: "bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20", desc: "Feature flags & toggles" },
  project:     { label: "Projects",         Icon: FolderKanban, color: "text-indigo-400",  badge: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20", desc: "Project management" },
  automation:  { label: "Automation",       Icon: Workflow,     color: "text-lime-400",    badge: "bg-lime-500/10 text-lime-400 border-lime-500/20",    desc: "Workflow automation" },
  custom:      { label: "Custom",           Icon: Wrench,       color: "text-muted-foreground", badge: "bg-muted text-muted-foreground border-border",  desc: "Custom tools" },
};

// Title-case an unknown category key ("agent_bus" → "Agent Bus") so categories
// not in the map above each get a distinct readable label instead of every one
// collapsing to "Custom".
const titleCaseCategory = (cat: string) =>
  cat.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const getCategoryConfig = (cat: string) =>
  CATEGORIES[cat] ?? { ...CATEGORIES.custom, label: titleCaseCategory(cat) };

// ─── Env var badge ────────────────────────────────────────────────────────────

function EnvBadge({ name }: { name: string }) {
  const copy = () => {
    copyToClipboard(name);
    toast.success("Copied");
  };
  return (
    <button
      onClick={(e) => { e.stopPropagation(); copy(); }}
      className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors"
      title="Click to copy"
    >
      {name}
    </button>
  );
}

// ─── Add tool dialog ──────────────────────────────────────────────────────────

const CATEGORY_OPTIONS = ["web", "browser", "file", "git", "github", "gitlab", "code", "docker", "api", "data", "integration", "ai", "custom"];

function AddToolDialog({ open, onClose }: { open: boolean; onClose: (tool?: Tool) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ key: "", name: "", description: "", category: "custom" });
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!form.key.trim() || !form.name.trim()) { toast.error("Key and name are required"); return; }
    setLoading(true);
    try {
      const res = await toolsApi.create({
        key: form.key, name: form.name,
        description: form.description || undefined, category: form.category,
      });
      qc.invalidateQueries({ queryKey: ["tools"] });
      toast.success("Tool created");
      setForm({ key: "", name: "", description: "", category: "custom" });
      onClose(res.data as Tool);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to create tool");
    } finally {
      setLoading(false);
    }
  };

  const SELECT_CLS = "w-full h-8 appearance-none text-sm bg-background text-foreground border border-input rounded-md px-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [color-scheme:dark]";

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose(undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold">Add Custom Tool</Dialog.Title>
            <Dialog.Close asChild>
              <button className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-4 h-4" /></button>
            </Dialog.Close>
          </div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Key (identifier)</label>
                <Input
                  placeholder="e.g. send_email"
                  value={form.key}
                  onChange={(e) => setForm((f) => ({ ...f, key: e.target.value.toLowerCase().replace(/\s/g, "_") }))}
                  className="h-8 text-sm font-mono"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Category</label>
                <select value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} className={SELECT_CLS}>
                  {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input placeholder="Human-readable name" value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className="h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Description (optional)</label>
              <Input placeholder="What this tool does" value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} className="h-8 text-sm" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={() => onClose(undefined)}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={loading}>
              {loading && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              Create Tool
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Category card ────────────────────────────────────────────────────────────

// ─── Tool row ─────────────────────────────────────────────────────────────────

function ToolRow({
  tool,
  onSelect,
  onDelete,
}: {
  tool: Tool;
  onSelect: () => void;
  onDelete?: () => void;
}) {
  const cfg = getCategoryConfig(tool.category);
  const envVars = tool.env_vars ?? [];

  return (
    <div
      onClick={onSelect}
      className="flex items-start gap-3 px-5 py-3.5 hover:bg-accent/30 transition-colors group cursor-pointer border-b border-border/60 last:border-0"
    >
      <div className={cn("w-8 h-8 rounded-lg border flex items-center justify-center shrink-0 mt-0.5", cfg.badge)}>
        <cfg.Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-medium text-foreground">{tool.name}</span>
          <code className="text-[11px] text-muted-foreground font-mono">{tool.key}</code>
          {tool.is_builtin && (
            <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>
          )}
        </div>
        {tool.description && (
          <p className="text-xs text-muted-foreground leading-snug line-clamp-1 mb-1">{tool.description}</p>
        )}
        {envVars.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[10px] text-muted-foreground">requires:</span>
            {envVars.map((v) => <EnvBadge key={v} name={v} />)}
          </div>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0 ml-2">
        {onDelete && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-destructive transition-all text-muted-foreground"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
        <ChevronRight className="w-4 h-4 text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ToolsPage() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [filterCat, setFilterCat] = useState("all");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<Tool | null>(null);
  const [importing, setImporting] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [envReqs, setEnvReqs] = useState<ToolEnvStatus[] | null>(null);
  const [envLabel, setEnvLabel] = useState<string>("");
  const [envVars, setEnvVars] = useState<RequiredEnvVar[] | null>(null);
  const pendingEnvVars = useRef<RequiredEnvVar[] | null>(null);
  const [showUrlInput, setShowUrlInput] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

  // Marketplace URL import + GitLab #158 risk-acknowledgment gate.
  const {
    importing: importingUrl,
    acknowledging,
    pendingRisk,
    runImport,
    confirmRisk,
    cancelRisk,
  } = useMarketplaceImport({
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["tools-builtin"] });
      qc.invalidateQueries({ queryKey: ["tools"] });
      setImportUrl("");
      setShowUrlInput(false);
      setEnvLabel(res.name);
      const needs = (res.python_requirements || []).filter((r) => r.env_hash && !r.provisioned);
      pendingEnvVars.current =
        res.required_env_vars && res.required_env_vars.length > 0 ? res.required_env_vars : null;
      if (needs.length > 0) {
        setEnvReqs(res.python_requirements || []);
      } else if (pendingEnvVars.current) {
        setEnvVars(pendingEnvVars.current);
        pendingEnvVars.current = null;
      }
    },
  });

  const { data: builtins = [], isLoading: loadingBuiltins } = useQuery<Tool[]>({
    queryKey: ["tools-builtin"],
    queryFn: () => toolsApi.builtin().then((r) => r.data),
  });

  const { data: custom = [], isLoading: loadingCustom } = useQuery<Tool[]>({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list().then((r) => r.data),
  });

  const isLoading = loadingBuiltins || loadingCustom;

  const del = useMutation({
    mutationFn: (id: string) => toolsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tools"] }); toast.success("Tool removed"); },
  });

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const res = await seedsApi.importZip(file, false);
      const { total, skipped } = res.data as { total: number; skipped: string[] };
      qc.invalidateQueries({ queryKey: ["tools-builtin"] });
      qc.invalidateQueries({ queryKey: ["tools"] });
      toast.success(`Imported ${total} file(s)${skipped.length ? `, ${skipped.length} skipped` : ""}`);
    } catch {
      toast.error("Import failed");
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  };

  // If any imported tool needs Python deps not yet provisioned, the onSuccess
  // handler prompts to install them first; the credentials modal opens after.
  const handleImportUrl = () => { void runImport(importUrl); };

  const builtinKeys = useMemo(() => new Set(builtins.map((b) => b.key)), [builtins]);
  // Deduplicate: hide custom DB tools whose key is already covered by a builtin
  const deduplicatedCustom = useMemo(() => custom.filter((t) => !builtinKeys.has(t.key)), [custom, builtinKeys]);

  // category counts across all tools
  const allTools = useMemo(() => [...builtins, ...deduplicatedCustom], [builtins, deduplicatedCustom]);

  const catCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of allTools) counts[t.category] = (counts[t.category] ?? 0) + 1;
    return counts;
  }, [allTools]);

  const presentCats = useMemo(() => Object.keys(catCounts).sort(), [catCounts]);

  const filteredBuiltins = useMemo(() =>
    builtins.filter((t) =>
      (filterCat === "all" || t.category === filterCat) &&
      (!search || t.name.toLowerCase().includes(search.toLowerCase()) || t.key.toLowerCase().includes(search.toLowerCase()) || (t.description ?? "").toLowerCase().includes(search.toLowerCase()))
    ), [builtins, filterCat, search]);

  const filteredCustom = useMemo(() =>
    deduplicatedCustom.filter((t) =>
      (filterCat === "all" || t.category === filterCat) &&
      (!search || t.name.toLowerCase().includes(search.toLowerCase()) || t.key.toLowerCase().includes(search.toLowerCase()) || (t.description ?? "").toLowerCase().includes(search.toLowerCase()))
    ), [deduplicatedCustom, filterCat, search]);

  const showBuiltins = filteredBuiltins.length > 0;
  const showCustom = filteredCustom.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <input ref={importRef} type="file" accept=".zip" className="hidden" onChange={handleImport} />
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold">Tools</h1>
          <p className="text-sm text-muted-foreground">
            {builtins.length} built-in · {deduplicatedCustom.length} custom
          </p>
        </div>
        <div className="flex items-center gap-2">
          {showUrlInput && (
            <div className="flex items-center gap-1">
              <Input
                autoFocus
                placeholder="Paste import link…"
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleImportUrl(); if (e.key === "Escape") { setShowUrlInput(false); setImportUrl(""); } }}
                className="h-8 text-sm w-64"
              />
              <Button size="sm" onClick={handleImportUrl} disabled={importingUrl || !importUrl.trim()}>
                {importingUrl ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Import"}
              </Button>
              <button onClick={() => { setShowUrlInput(false); setImportUrl(""); }} className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-3.5 h-3.5" /></button>
            </div>
          )}
          <Button size="sm" variant="outline" onClick={() => { setShowUrlInput((v) => !v); setImportUrl(""); }} className="gap-1.5">
            <Link className="w-3.5 h-3.5" />
            Import URL
          </Button>
          <Button size="sm" variant="outline" onClick={() => importRef.current?.click()} disabled={importing} className="gap-1.5">
            {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            Import ZIP
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />Custom Tool
          </Button>
        </div>
      </div>

      {/* Category filter pills */}
      {!isLoading && presentCats.length > 0 && (
        <div className="px-6 py-2 border-b border-border flex items-center gap-2 flex-wrap shrink-0">
          <button
            onClick={() => setFilterCat("all")}
            className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors", filterCat === "all" ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}
          >
            All ({allTools.length})
          </button>
          {presentCats.map((cat) => {
            const cfg = getCategoryConfig(cat);
            return (
              <button
                key={cat}
                onClick={() => setFilterCat(filterCat === cat ? "all" : cat)}
                className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors", filterCat === cat ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}
              >
                {cfg.label} ({catCounts[cat] ?? 0})
              </button>
            );
          })}
        </div>
      )}

      {/* Search bar */}
      <div className="px-6 py-2.5 border-b border-border shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, key, or description…"
            className="pl-8 h-8 text-sm"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
          </div>
        ) : !showBuiltins && !showCustom ? (
          <div className="flex flex-col items-center justify-center h-60 gap-3 text-muted-foreground">
            <Wrench className="w-10 h-10 opacity-20" />
            <p className="text-sm">{search ? "No tools match your search" : "No tools yet"}</p>
            {!search && (
              <Button size="sm" variant="outline" onClick={() => setAddOpen(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Add your first tool
              </Button>
            )}
          </div>
        ) : (
          <>
            {showBuiltins && (
              <div>
                <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Developer Suite — Built-in ({filteredBuiltins.length})
                  </span>
                </div>
                {filteredBuiltins.map((tool) => (
                  <ToolRow key={tool.id} tool={tool} onSelect={() => setDetail(tool)} />
                ))}
              </div>
            )}

            {showCustom && (
              <div>
                <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
                  <Wrench className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Custom Tools ({filteredCustom.length})
                  </span>
                </div>
                {filteredCustom.map((tool) => (
                  <ToolRow
                    key={tool.id}
                    tool={tool}
                    onSelect={() => setDetail(tool)}
                    onDelete={() => del.mutate(tool.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <AddToolDialog open={addOpen} onClose={(tool) => { setAddOpen(false); if (tool) setDetail(tool); }} />
      {detail && <ToolDetailPanel tool={detail} onClose={() => setDetail(null)} />}
      <ToolEnvModal
        open={envReqs !== null}
        onClose={() => {
          setEnvReqs(null);
          if (pendingEnvVars.current) {
            setEnvVars(pendingEnvVars.current);
            pendingEnvVars.current = null;
          }
        }}
        requirements={envReqs || []}
        label={envLabel}
      />
      <EnvVarModal
        open={envVars !== null}
        onClose={() => setEnvVars(null)}
        required={envVars || []}
        label={envLabel}
      />
      <RiskAckDialog
        risk={pendingRisk}
        busy={acknowledging}
        onConfirm={confirmRisk}
        onCancel={cancelRisk}
      />
    </div>
  );
}
