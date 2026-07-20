"use client";
import { useState, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { personasApi, seedsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Fingerprint, Plus, Loader2, Trash2, Zap, Network, Wrench,
  ChevronRight, Sparkles, Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, FilterBar, PageSearch, PageLoading, PageEmpty, SectionLabel,
} from "@/components/layout/page-shell";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import { PersonaDetailPanel, type Persona } from "@/components/personas/PersonaDetailPanel";

const COMMON_ICONS = ["💻","🧪","🔬","🎨","⚙️","📋","✨","🤖","🧠","🔧","🚀","🎯","📊","🔐","🌐"];

// ─── Create dialog ────────────────────────────────────────────────────────────

function CreatePersonaDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ key: "", name: "", description: "", icon: "✨" });
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!form.key.trim() || !form.name.trim()) { toast.error("Key and name are required"); return; }
    setLoading(true);
    try {
      await personasApi.create({
        key: form.key.trim(), name: form.name.trim(),
        description: form.description.trim() || undefined,
        icon: form.icon, soul: {}, system_prompt: "",
        default_skills: [], default_tools: [], default_mcps: [],
      });
      qc.invalidateQueries({ queryKey: ["personas"] });
      toast.success("Persona created");
      onClose();
      setForm({ key: "", name: "", description: "", icon: "✨" });
    } catch { toast.error("Failed to create persona"); }
    finally { setLoading(false); }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-2xl shadow-2xl p-6 space-y-4">
          <Dialog.Title className="text-base font-semibold">New Persona</Dialog.Title>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Key *</label>
              <Input placeholder="my_persona" value={form.key}
                onChange={(e) => setForm((f) => ({ ...f, key: e.target.value.toLowerCase().replace(/\s+/g, "_") }))}
                className="font-mono" autoFocus />
              <p className="text-[10px] text-muted-foreground">Unique identifier, snake_case</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Name *</label>
              <Input placeholder="My Persona" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Description</label>
              <Input placeholder="What this persona is for…" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Icon</label>
              <Input value={form.icon} onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))} placeholder="emoji" className="font-mono" maxLength={4} />
              <div className="flex flex-wrap gap-1 mt-1">
                {COMMON_ICONS.map((emoji) => (
                  <button key={emoji} onClick={() => setForm((f) => ({ ...f, icon: emoji }))}
                    className={cn("w-7 h-7 rounded text-base flex items-center justify-center transition-colors", form.icon === emoji ? "bg-primary/20 ring-1 ring-primary" : "hover:bg-accent")}>
                    {emoji}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="flex justify-between pt-2">
            <Button variant="ghost" onClick={onClose} disabled={loading}>Cancel</Button>
            <Button onClick={handleCreate} disabled={loading}>
              {loading && <Loader2 className="w-4 h-4 animate-spin mr-1.5" />}
              Create Persona
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Persona row ──────────────────────────────────────────────────────────────

function PersonaRow({ persona, onClick, onDelete }: {
  persona: Persona;
  onClick: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-4 px-5 py-3.5 hover:bg-accent/30 transition-colors group cursor-pointer border-b border-border/60 last:border-0"
    >
      {/* Icon */}
      <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-lg shrink-0">
        {persona.icon || "✨"}
      </div>

      {/* Name + key + description */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-medium text-foreground">{persona.name}</span>
          <code className="text-[11px] text-muted-foreground font-mono">{persona.key}</code>
          {persona.is_builtin && <Badge variant="secondary" className="text-[10px] h-4 px-1.5">built-in</Badge>}
        </div>
        {persona.description && (
          <p className="text-xs text-muted-foreground leading-snug line-clamp-1">{persona.description}</p>
        )}
        {persona.soul?.personality && !persona.description && (
          <p className="text-xs text-muted-foreground italic line-clamp-1">{persona.soul.personality}</p>
        )}
      </div>

      {/* Capability counts */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground shrink-0">
        {persona.default_skills.length > 0 && (
          <span className="flex items-center gap-1">
            <Zap className="w-3 h-3" />{persona.default_skills.length}
          </span>
        )}
        {persona.default_mcps.length > 0 && (
          <span className="flex items-center gap-1">
            <Network className="w-3 h-3" />{persona.default_mcps.length}
          </span>
        )}
        {persona.default_tools.length > 0 && (
          <span className="flex items-center gap-1">
            <Wrench className="w-3 h-3" />{persona.default_tools.length}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 shrink-0">
        {!persona.is_builtin && onDelete && (
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

type FilterType = "all" | "builtin" | "custom";

export default function PersonasPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<Persona | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");

  const importRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  const { data: builtinPersonas = [], isLoading: loadingBuiltin } = useQuery<Persona[]>({
    queryKey: ["personas-builtin"],
    queryFn: () => personasApi.builtin().then((r) => r.data),
  });

  const { data: customPersonas = [], isLoading: loadingCustom } = useQuery<Persona[]>({
    queryKey: ["personas"],
    queryFn: () => personasApi.list().then((r) => r.data),
  });

  const deletePersona = useMutation({
    mutationFn: (id: string) => personasApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["personas"] }); toast.success("Persona deleted"); },
  });

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const res = await seedsApi.importZip(file, false);
      const { total, skipped } = res.data as { total: number; skipped: string[] };
      qc.invalidateQueries({ queryKey: ["personas-builtin"] });
      qc.invalidateQueries({ queryKey: ["personas"] });
      toast.success(`Imported ${total} file(s)${skipped.length ? `, ${skipped.length} skipped` : ""}`);
    } catch {
      toast.error("Import failed");
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  };

  const isLoading = loadingBuiltin || loadingCustom;
  const builtinKeys = useMemo(() => new Set(builtinPersonas.map((p) => p.key)), [builtinPersonas]);
  const deduplicatedCustom = useMemo(() => customPersonas.filter((p) => !builtinKeys.has(p.key)), [customPersonas, builtinKeys]);
  const allPersonas = [...builtinPersonas, ...deduplicatedCustom];

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return allPersonas.filter((p) => {
      const matchesSearch = !q || p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q) || p.key.includes(q);
      const matchesFilter = filter === "all" || (filter === "builtin" ? p.is_builtin : !p.is_builtin);
      return matchesSearch && matchesFilter;
    });
  }, [allPersonas, search, filter]);  // allPersonas already deduped

  const filteredBuiltin = filtered.filter((p) => p.is_builtin);
  const filteredCustom = filtered.filter((p) => !p.is_builtin);

  const FILTERS: { id: FilterType; label: string; count: number }[] = [
    { id: "all", label: "All", count: allPersonas.length },
    { id: "builtin", label: "Built-in", count: builtinPersonas.length },
    { id: "custom", label: "Custom", count: deduplicatedCustom.length },
  ];

  return (
    <PageShell>
      <PageHeader
        icon={Fingerprint}
        title="Personas"
        subtitle={`${builtinPersonas.length} built-in · ${deduplicatedCustom.length} custom`}
        actions={
          <>
            <input ref={importRef} type="file" accept=".zip" className="hidden" onChange={handleImport} />
            <Button size="sm" variant="outline" onClick={() => importRef.current?.click()} disabled={importing} className="gap-1.5">
              {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              Import ZIP
            </Button>
            <Button onClick={() => setShowCreate(true)} size="sm" className="gap-1.5">
              <Plus className="w-3.5 h-3.5" />New Persona
            </Button>
          </>
        }
      />

      <FilterBar options={FILTERS} value={filter} onChange={setFilter} />

      <PageSearch
        value={search}
        onChange={setSearch}
        placeholder="Search by name, key, or description…"
      />

      <PageBody>
        {isLoading ? (
          <PageLoading />
        ) : filtered.length === 0 ? (
          <PageEmpty
            icon={Fingerprint}
            message={search ? "No personas match your search" : "No personas yet"}
          >
            {!search && (
              <Button size="sm" variant="outline" onClick={() => setShowCreate(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Create your first persona
              </Button>
            )}
          </PageEmpty>
        ) : (
          <>
            {filteredBuiltin.length > 0 && (
              <div>
                <SectionLabel icon={Sparkles} label="Built-in" count={filteredBuiltin.length} />
                {filteredBuiltin.map((p) => (
                  <PersonaRow key={p.id} persona={p} onClick={() => setSelected(p)} />
                ))}
              </div>
            )}
            {filteredCustom.length > 0 && (
              <div>
                <SectionLabel icon={Fingerprint} label="Custom" count={filteredCustom.length} />
                {filteredCustom.map((p) => (
                  <PersonaRow key={p.id} persona={p} onClick={() => setSelected(p)} onDelete={() => deletePersona.mutate(p.id)} />
                ))}
              </div>
            )}
          </>
        )}
      </PageBody>

      <CreatePersonaDialog open={showCreate} onClose={() => setShowCreate(false)} />
      {selected && <PersonaDetailPanel persona={selected} onClose={() => setSelected(null)} />}
    </PageShell>
  );
}
