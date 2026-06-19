"use client";
import { useState, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { skillsApi, seedsApi, type ToolEnvStatus } from "@/lib/api";
import { ToolEnvModal } from "@/components/tools/ToolEnvModal";
import { EnvVarModal, type RequiredEnvVar } from "@/components/tools/EnvVarModal";
import { RiskAckDialog } from "@/components/marketplace/RiskAckDialog";
import { useMarketplaceImport } from "@/components/marketplace/useMarketplaceImport";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Loader2, Plus, Trash2, Sparkles, X, ChevronRight, Upload, Download, Link, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import { SkillDetailPanel } from "@/components/skills/SkillDetailPanel";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

const CATEGORY_COLORS: Record<string, string> = {
  code:       "bg-blue-500/10 text-blue-400 border-blue-500/20",
  file:       "bg-amber-500/10 text-amber-400 border-amber-500/20",
  web:        "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  git:        "bg-violet-500/10 text-violet-400 border-violet-500/20",
  data:       "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  ai:         "bg-pink-500/10 text-pink-400 border-pink-500/20",
  integration:"bg-orange-500/10 text-orange-400 border-orange-500/20",
  custom:     "bg-muted text-muted-foreground border-border",
};

interface Skill {
  id: string;
  key: string;
  name: string;
  description: string | null;
  category: string;
  is_builtin: boolean;
  files?: Record<string, string>;
}

interface BuiltinSkill {
  key: string;
  name: string;
  description: string;
  category: string;
  is_builtin: boolean;
  files?: Record<string, string>;
}

const CATEGORIES = ["code", "file", "web", "git", "data", "ai", "integration", "custom"];

function AddSkillDialog({ open, onClose }: { open: boolean; onClose: (skill?: unknown) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ key: "", name: "", description: "", category: "custom" });
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!form.key.trim() || !form.name.trim()) { toast.error("Key and name are required"); return; }
    setLoading(true);
    try {
      const res = await skillsApi.create({ key: form.key, name: form.name, description: form.description || undefined, category: form.category });
      qc.invalidateQueries({ queryKey: ["skills"] });
      toast.success("Skill created");
      setForm({ key: "", name: "", description: "", category: "custom" });
      onClose(res.data);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to create skill");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose(undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold">Add Custom Skill</Dialog.Title>
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
                <select
                  value={form.category}
                  onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                  className="w-full h-8 appearance-none text-sm bg-background text-foreground border border-input rounded-md px-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [color-scheme:dark]"
                >
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input
                placeholder="Human-readable name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Description (optional)</label>
              <Input
                placeholder="What this skill does"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                className="h-8 text-sm"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={() => onClose(undefined)}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={loading}>
              {loading && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              Create Skill
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SkillCard({
  skill, onDelete, onClick,
}: {
  skill: Skill | BuiltinSkill & { id?: string; is_builtin: boolean };
  onDelete?: () => void;
  onClick?: () => void;
}) {
  const s = skill as Skill;
  const catColor = CATEGORY_COLORS[s.category] ?? CATEGORY_COLORS.custom;
  return (
    <div
      className="flex items-start justify-between gap-3 px-4 py-3 hover:bg-accent/30 transition-colors group cursor-pointer"
      onClick={onClick}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-medium">{s.name}</span>
          <code className="text-xs text-muted-foreground font-mono">{s.key}</code>
          <Badge variant="outline" className={cn("text-[10px] h-4 px-1.5", catColor)}>{s.category}</Badge>
          {s.is_builtin && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>}
        </div>
        {s.description && <p className="text-xs text-muted-foreground">{s.description}</p>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {!s.is_builtin && onDelete && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-destructive transition-all"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
        <ChevronRight className="w-4 h-4 text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-all" />
      </div>
    </div>
  );
}

export default function SkillsPage() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [filterCat, setFilterCat] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [importing, setImporting] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [showUrlInput, setShowUrlInput] = useState(false);
  const [envReqs, setEnvReqs] = useState<ToolEnvStatus[] | null>(null);
  const [envLabel, setEnvLabel] = useState<string>("");
  const [envVars, setEnvVars] = useState<RequiredEnvVar[] | null>(null);
  const pendingEnvVars = useRef<RequiredEnvVar[] | null>(null);
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
      qc.invalidateQueries({ queryKey: ["skills-builtin"] });
      qc.invalidateQueries({ queryKey: ["skills"] });
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

  const { data: builtins = [], isLoading: loadingBuiltins } = useQuery<BuiltinSkill[]>({
    queryKey: ["skills-builtin"],
    queryFn: () => skillsApi.builtin().then((r) => r.data),
  });

  const { data: custom = [], isLoading: loadingCustom } = useQuery<Skill[]>({
    queryKey: ["skills"],
    queryFn: () => skillsApi.list().then((r) => r.data),
  });

  const deleteSkill = useMutation({
    mutationFn: (id: string) => skillsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["skills"] }); toast.success("Skill removed"); },
    onError: () => toast.error("Failed to delete skill"),
  });

  const builtinKeys = useMemo(() => new Set(builtins.map((b) => b.key)), [builtins]);
  // Filesystem seeds (builtins endpoint) already carry correct is_builtin from API
  const allBuiltins: Skill[] = useMemo(() => builtins.map((b) => ({
    ...b,
    id: `builtin:${b.key}`,
    description: b.description ?? null,
    // is_builtin comes from API: true for seeds/builtin/, false for seeds/custom/
  })), [builtins]);
  // Deduplicate: hide DB custom skills whose key is already in the filesystem
  const deduplicatedCustom = useMemo(() => custom.filter((s) => !builtinKeys.has(s.key)), [custom, builtinKeys]);
  const allSkills = useMemo(() => [...allBuiltins, ...deduplicatedCustom], [allBuiltins, deduplicatedCustom]);

  // category counts across all skills (deduped category list w/ counts)
  const catCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of allSkills) counts[s.category] = (counts[s.category] ?? 0) + 1;
    return counts;
  }, [allSkills]);
  const presentCats = useMemo(() => Object.keys(catCounts).sort(), [catCounts]);

  const matches = (s: Skill) => {
    if (filterCat !== "all" && s.category !== filterCat) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return s.name.toLowerCase().includes(q) || s.key.toLowerCase().includes(q) || (s.description ?? "").toLowerCase().includes(q);
  };
  const filteredBuiltin = useMemo(() => allBuiltins.filter((s) => s.is_builtin && matches(s)), [allBuiltins, filterCat, search]);
  const filteredCustom = useMemo(() => [...allBuiltins.filter((s) => !s.is_builtin), ...deduplicatedCustom].filter(matches), [allBuiltins, deduplicatedCustom, filterCat, search]);
  const showBuiltins = filteredBuiltin.length > 0;
  const showCustom = filteredCustom.length > 0;

  const isLoading = loadingBuiltins || loadingCustom;

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const res = await seedsApi.importZip(file, false);
      const { total, skipped } = res.data as { total: number; skipped: string[] };
      qc.invalidateQueries({ queryKey: ["skills-builtin"] });
      qc.invalidateQueries({ queryKey: ["skills"] });
      toast.success(`Imported ${total} file(s)${skipped.length ? `, ${skipped.length} skipped` : ""}`);
    } catch {
      toast.error("Import failed");
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  };

  const handleImportUrl = () => { void runImport(importUrl); };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold">Skills</h1>
          <p className="text-sm text-muted-foreground">{allBuiltins.length} built-in · {deduplicatedCustom.length} custom</p>
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
          <input ref={importRef} type="file" accept=".zip" className="hidden" onChange={handleImport} />
          <Button size="sm" variant="outline" onClick={() => { setShowUrlInput((v) => !v); setImportUrl(""); }} className="gap-1.5">
            <Link className="w-3.5 h-3.5" />
            Import URL
          </Button>
          <Button size="sm" variant="outline" onClick={() => importRef.current?.click()} disabled={importing} className="gap-1.5">
            {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            Import ZIP
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />
            Add Skill
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
            All ({allSkills.length})
          </button>
          {presentCats.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCat(filterCat === cat ? "all" : cat)}
              className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors", filterCat === cat ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}
            >
              {cat} ({catCounts[cat] ?? 0})
            </button>
          ))}
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

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading skills…
          </div>
        ) : !showBuiltins && !showCustom ? (
          <div className="flex flex-col items-center justify-center h-60 gap-3 text-muted-foreground">
            <Sparkles className="w-10 h-10 opacity-20" />
            <p className="text-sm">{search || filterCat !== "all" ? "No skills match your filters" : "No skills yet"}</p>
          </div>
        ) : (
          <>
            {showBuiltins && (
              <div>
                <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Built-in ({filteredBuiltin.length})
                  </span>
                </div>
                {filteredBuiltin.map((s) => (
                  <SkillCard key={s.key} skill={s} onClick={() => setDetailSkill(s)} />
                ))}
              </div>
            )}
            {showCustom && (
              <div>
                <div className="px-5 py-2 bg-accent/20 border-b border-border/60 flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                    Custom ({filteredCustom.length})
                  </span>
                </div>
                {filteredCustom.map((s) => (
                  <SkillCard
                    key={s.key}
                    skill={s}
                    onDelete={s.is_builtin ? undefined : () => deleteSkill.mutate(s.id)}
                    onClick={() => setDetailSkill(s)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <AddSkillDialog open={addOpen} onClose={(skill) => {
        setAddOpen(false);
        if (skill) setDetailSkill(skill as Skill);
      }} />

      {detailSkill && (
        <SkillDetailPanel
          skill={detailSkill}
          onClose={() => setDetailSkill(null)}
        />
      )}
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
