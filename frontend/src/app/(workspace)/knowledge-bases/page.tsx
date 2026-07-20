"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { knowledgeBasesApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Loader2, Plus, Trash2, BookOpen, X, ChevronRight, FileText, Settings2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, PageSearch, PageLoading, PageEmpty, SectionLabel,
} from "@/components/layout/page-shell";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";

const VALID_STRATEGIES = ["fixed", "sentence", "paragraph"] as const;
type ChunkStrategy = typeof VALID_STRATEGIES[number];

interface KnowledgeBase {
  id: string;
  org_id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  chunk_strategy: string;
  chunk_size: number;
  chunk_overlap: number;
  file_count: number;
}

// ─── Create dialog ────────────────────────────────────────────────────────────

function CreateKBDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", description: "" });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [strategy, setStrategy] = useState<ChunkStrategy>("fixed");
  const [chunkSize, setChunkSize] = useState(512);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [loading, setLoading] = useState(false);

  const maxOverlap = Math.floor(chunkSize / 2);

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    setLoading(true);
    try {
      await knowledgeBasesApi.create({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        chunk_strategy: strategy,
        chunk_size: chunkSize,
        chunk_overlap: Math.min(chunkOverlap, maxOverlap),
      });
      toast.success("Knowledge base created");
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
      setForm({ name: "", description: "" });
      setStrategy("fixed");
      setChunkSize(512);
      setChunkOverlap(50);
      setShowAdvanced(false);
      onClose();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to create knowledge base");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold">New Knowledge Base</Dialog.Title>
            <Dialog.Close asChild>
              <button className="p-1 rounded hover:bg-accent text-muted-foreground">
                <X className="w-4 h-4" />
              </button>
            </Dialog.Close>
          </div>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Product Docs"
                className="h-8 text-sm"
                onKeyDown={(e) => e.key === "Enter" && !showAdvanced && handleCreate()}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Description (optional)</label>
              <Input
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="What this knowledge base contains"
                className="h-8 text-sm"
              />
            </div>

            {/* Advanced chunking toggle */}
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <Settings2 className="w-3.5 h-3.5" />
              {showAdvanced ? "Hide" : "Show"} chunking options
            </button>

            {showAdvanced && (
              <div className="space-y-3 border border-border rounded-lg p-3 bg-accent/5">
                {/* Strategy */}
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground font-medium">Strategy</label>
                  <div className="grid grid-cols-3 gap-1.5">
                    {VALID_STRATEGIES.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setStrategy(s)}
                        className={cn(
                          "px-2 py-1.5 rounded border text-xs font-medium transition-colors capitalize",
                          strategy === s
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border hover:bg-accent/20 text-muted-foreground"
                        )}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
                {/* Chunk size */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <label className="text-xs text-muted-foreground font-medium">Chunk Size</label>
                    <span className="text-xs font-mono">{chunkSize} chars</span>
                  </div>
                  <input
                    type="range" min={64} max={2048} step={64}
                    value={chunkSize}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setChunkSize(v);
                      if (chunkOverlap > Math.floor(v / 2)) setChunkOverlap(Math.floor(v / 2));
                    }}
                    className="w-full accent-primary"
                  />
                </div>
                {/* Overlap */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <label className="text-xs text-muted-foreground font-medium">Overlap</label>
                    <span className="text-xs font-mono">{Math.min(chunkOverlap, maxOverlap)} chars</span>
                  </div>
                  <input
                    type="range" min={0} max={maxOverlap}
                    step={Math.max(1, Math.floor(maxOverlap / 20))}
                    value={Math.min(chunkOverlap, maxOverlap)}
                    onChange={(e) => setChunkOverlap(Number(e.target.value))}
                    className="w-full accent-primary"
                  />
                </div>
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={loading}>
              {loading && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              Create
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function KnowledgeBasesPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const [createOpen, setCreateOpen] = useState(false);
  const [search, setSearch] = useState("");

  const { data: kbs = [], isLoading } = useQuery<KnowledgeBase[]>({
    queryKey: ["knowledge-bases"],
    queryFn: () => knowledgeBasesApi.list().then((r) => r.data),
  });

  const del = useMutation({
    mutationFn: (id: string) => knowledgeBasesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["knowledge-bases"] });
      toast.success("Knowledge base deleted");
    },
    onError: () => toast.error("Failed to delete knowledge base"),
  });

  const filtered = kbs.filter((kb) =>
    !search ||
    kb.name.toLowerCase().includes(search.toLowerCase()) ||
    (kb.description ?? "").toLowerCase().includes(search.toLowerCase())
  );

  const totalFiles = kbs.reduce((acc, kb) => acc + kb.file_count, 0);

  return (
    <PageShell>
      <PageHeader
        icon={BookOpen}
        title="Knowledge Bases"
        subtitle={`${kbs.length} base${kbs.length !== 1 ? "s" : ""} · ${totalFiles} document${totalFiles !== 1 ? "s" : ""}`}
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />
            New Knowledge Base
          </Button>
        }
      />

      <PageSearch
        value={search}
        onChange={setSearch}
        placeholder="Search knowledge bases…"
      />

      <PageBody>
        {isLoading ? (
          <PageLoading />
        ) : filtered.length === 0 ? (
          <PageEmpty
            icon={BookOpen}
            message={search ? "No knowledge bases match your search" : "No knowledge bases yet"}
          >
            {!search && (
              <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />Create your first knowledge base
              </Button>
            )}
          </PageEmpty>
        ) : (
          <div>
            <SectionLabel
              icon={BookOpen}
              label={search ? `${filtered.length} of ${kbs.length} bases` : `${kbs.length} knowledge base${kbs.length !== 1 ? "s" : ""}`}
            />
            {filtered.map((kb) => (
              <div
                key={kb.id}
                className="flex items-center gap-4 px-5 py-4 border-b border-border/60 last:border-0 hover:bg-accent/20 transition-colors group cursor-pointer"
                onClick={() => router.push(`/knowledge-bases/${kb.id}`)}
              >
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <BookOpen className="w-4 h-4 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-medium">{kb.name}</span>
                  </div>
                  {kb.description && (
                    <p className="text-xs text-muted-foreground truncate">{kb.description}</p>
                  )}
                  <div className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                    <FileText className="w-3 h-3" />
                    <span>{kb.file_count} document{kb.file_count !== 1 ? "s" : ""}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${kb.name}"? This cannot be undone.`)) {
                        del.mutate(kb.id);
                      }
                    }}
                    className={cn(
                      "opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-accent",
                      "text-muted-foreground hover:text-destructive transition-all"
                    )}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                  <ChevronRight className="w-4 h-4 text-muted-foreground/40" />
                </div>
              </div>
            ))}
          </div>
        )}
      </PageBody>

      <CreateKBDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </PageShell>
  );
}
