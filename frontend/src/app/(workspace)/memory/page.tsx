"use client";
import { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { memoryNotesApi, MemoryNoteSummary, MemoryGraph } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Loader2, Plus, Trash2, X, Search, Folder, FileText, Hash, Pencil, Save,
  BrainCircuit, Network, FolderOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";

// react-force-graph-3d pulls in three.js / WebGL — client only.
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

// Loose shapes (index signature) so force-graph's NodeObject/LinkObject are assignable.
type GNode = { [k: string]: unknown; id?: string | number; type?: string; label?: string };
type GLink = { [k: string]: unknown; type?: string };

function folderOf(path: string): string {
  return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
}
function fileOf(path: string): string {
  return path.includes("/") ? path.slice(path.lastIndexOf("/") + 1) : path;
}

// ─── Note editor / viewer modal ────────────────────────────────────────────────

function NoteModal({ noteId, onClose }: { noteId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: "", path: "", body_md: "", tags: "" });

  const { data: note, isLoading } = useQuery({
    queryKey: ["memory-note", noteId],
    queryFn: async () => {
      const r = await memoryNotesApi.get(noteId);
      setForm({
        title: r.data.title, path: r.data.path, body_md: r.data.body_md,
        tags: (r.data.tags || []).join(", "),
      });
      return r.data;
    },
  });

  const save = useMutation({
    mutationFn: () => memoryNotesApi.update(noteId, {
      title: form.title, path: form.path, body_md: form.body_md,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      toast.success("Saved");
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["memory-note", noteId] });
      qc.invalidateQueries({ queryKey: ["memory-notes"] });
      qc.invalidateQueries({ queryKey: ["memory-graph"] });
    },
    onError: () => toast.error("Save failed"),
  });

  const del = useMutation({
    mutationFn: () => memoryNotesApi.delete(noteId),
    onSuccess: () => {
      toast.success("Deleted");
      qc.invalidateQueries({ queryKey: ["memory-notes"] });
      qc.invalidateQueries({ queryKey: ["memory-graph"] });
      onClose();
    },
    onError: () => toast.error("Delete failed"),
  });

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(820px,92vw)] max-h-[88vh] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-xl border border-border bg-card shadow-2xl flex flex-col">
          {isLoading || !note ? (
            <div className="flex items-center justify-center h-64"><Loader2 className="w-6 h-6 animate-spin" /></div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
                  {editing ? (
                    <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="h-8" />
                  ) : (
                    <Dialog.Title className="font-semibold truncate">{note.title}</Dialog.Title>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {editing ? (
                    <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                      {save.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                      <span className="ml-1">Save</span>
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(true)}><Pencil className="w-4 h-4" /></Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => { if (confirm("Delete this note?")) del.mutate(); }}>
                    <Trash2 className="w-4 h-4 text-red-500" />
                  </Button>
                  <Dialog.Close asChild><Button size="sm" variant="ghost"><X className="w-4 h-4" /></Button></Dialog.Close>
                </div>
              </div>

              <div className="overflow-y-auto px-5 py-4 flex-1">
                {editing ? (
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs text-muted-foreground">Path (virtual folder)</label>
                      <Input value={form.path} onChange={(e) => setForm({ ...form, path: e.target.value })} className="h-8 font-mono text-xs" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">Tags (comma-separated)</label>
                      <Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="h-8" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">Markdown — use [[Note Title]] to link, #tag for topics</label>
                      <textarea
                        value={form.body_md}
                        onChange={(e) => setForm({ ...form, body_md: e.target.value })}
                        className="w-full h-72 rounded-md border border-border bg-background p-3 font-mono text-sm resize-y"
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="mb-2 font-mono text-xs text-muted-foreground">{note.path}</div>
                    {(note.tags || []).length > 0 && (
                      <div className="mb-3 flex flex-wrap gap-1.5">
                        {note.tags.map((t) => (
                          <span key={t} className="inline-flex items-center gap-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                            <Hash className="w-3 h-3" />{t}
                          </span>
                        ))}
                      </div>
                    )}
                    <article className="prose prose-sm prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.body_md || "_empty_"}</ReactMarkdown>
                    </article>
                  </>
                )}
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Manage view ────────────────────────────────────────────────────────────────

function ManageView({ onOpen }: { onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);

  const { data: notes = [], isLoading } = useQuery({
    queryKey: ["memory-notes"],
    queryFn: async () => (await memoryNotesApi.list()).data,
  });

  const folders = useMemo(() => {
    const s = new Set<string>();
    notes.forEach((n) => { const f = folderOf(n.path); if (f) s.add(f); });
    return Array.from(s).sort();
  }, [notes]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return notes.filter((n) => {
      if (activeFolder !== null && folderOf(n.path) !== activeFolder) return false;
      if (q && !n.title.toLowerCase().includes(q) && !n.path.toLowerCase().includes(q)
          && !(n.tags || []).some((t) => t.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [notes, search, activeFolder]);

  const create = useMutation({
    mutationFn: () => memoryNotesApi.create({
      title: "Untitled", body_md: "", path: activeFolder ? `${activeFolder}/untitled.md` : "untitled.md",
    }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["memory-notes"] }); onOpen(r.data.id); },
    onError: () => toast.error("Create failed"),
  });

  const moveToFolder = useCallback(async (id: string, folder: string) => {
    const note = notes.find((n) => n.id === id);
    if (!note) return;
    const newPath = folder ? `${folder}/${fileOf(note.path)}` : fileOf(note.path);
    if (newPath === note.path) return;
    try {
      await memoryNotesApi.move(id, newPath);
      qc.invalidateQueries({ queryKey: ["memory-notes"] });
      qc.invalidateQueries({ queryKey: ["memory-graph"] });
      toast.success(`Moved to ${folder || "root"}`);
    } catch { toast.error("Move failed"); }
  }, [notes, qc]);

  return (
    <div className="flex gap-4 h-full min-h-0">
      {/* Folder rail */}
      <aside className="w-56 shrink-0 border-r border-border pr-3 overflow-y-auto">
        <FolderRow label="All notes" icon={FolderOpen} active={activeFolder === null}
          onClick={() => setActiveFolder(null)} onDropNote={(id) => moveToFolder(id, "")} />
        {folders.map((f) => (
          <FolderRow key={f} label={f} icon={Folder} active={activeFolder === f}
            onClick={() => setActiveFolder(f)} onDropNote={(id) => moveToFolder(id, f)} />
        ))}
      </aside>

      {/* Notes */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search title, path, tag…" className="pl-8 h-9" />
          </div>
          <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
            <Plus className="w-4 h-4 mr-1" /> New note
          </Button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-64"><Loader2 className="w-6 h-6 animate-spin" /></div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-muted-foreground text-sm gap-2">
            <BrainCircuit className="w-8 h-8 opacity-40" />
            No memory notes yet. Agents write these as they work — or create one.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 overflow-y-auto pb-4">
            {filtered.map((n) => (
              <button
                key={n.id}
                draggable
                onDragStart={(e) => { e.dataTransfer.setData("text/plain", n.id); setDragId(n.id); }}
                onDragEnd={() => setDragId(null)}
                onClick={() => onOpen(n.id)}
                className={cn(
                  "text-left rounded-lg border border-border bg-card p-3 hover:border-primary/50 transition cursor-pointer",
                  dragId === n.id && "opacity-50",
                )}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className="font-medium text-sm truncate">{n.title}</span>
                </div>
                <div className="font-mono text-[11px] text-muted-foreground truncate mb-2">{n.path}</div>
                {(n.tags || []).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {n.tags.slice(0, 4).map((t) => (
                      <span key={t} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">#{t}</span>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FolderRow({ label, icon: Icon, active, onClick, onDropNote }: {
  label: string; icon: React.ElementType; active: boolean;
  onClick: () => void; onDropNote: (id: string) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      onClick={onClick}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const id = e.dataTransfer?.getData("text/plain"); if (id) onDropNote(id); }}
      className={cn(
        "flex items-center gap-2 rounded px-2 py-1.5 text-sm cursor-pointer mb-0.5",
        active ? "bg-primary/15 text-primary" : "hover:bg-muted text-foreground/80",
        over && "ring-1 ring-primary",
      )}
    >
      <Icon className="w-4 h-4 shrink-0" />
      <span className="truncate font-mono text-xs">{label}</span>
    </div>
  );
}

// ─── 3D graph view ──────────────────────────────────────────────────────────────

function GraphView({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["memory-graph"],
    queryFn: async () => (await memoryNotesApi.graph()).data,
  });

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    // clone — force-graph mutates link source/target into node refs
    return {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    };
  }, [data]);

  if (isLoading) return <div className="flex items-center justify-center h-full"><Loader2 className="w-6 h-6 animate-spin" /></div>;
  if (!data || data.nodes.length === 0)
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm gap-2">
        <Network className="w-8 h-8 opacity-40" />
        No graph yet — create notes with [[links]] and #tags.
      </div>
    );

  return (
    <div className="h-full w-full rounded-lg border border-border overflow-hidden bg-black/40">
      <ForceGraph3D
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        nodeLabel={(n: GNode) => n.label || ""}
        nodeColor={(n: GNode) => (n.type === "tag" ? "#a855f7" : "#38bdf8")}
        nodeVal={(n: GNode) => (n.type === "tag" ? 2 : 4)}
        linkColor={(l: GLink) => (l.type === "tag" ? "rgba(168,85,247,0.35)" : "rgba(56,189,248,0.55)")}
        linkWidth={0.6}
        linkDirectionalParticles={(l: GLink) => (l.type === "wikilink" ? 2 : 0)}
        linkDirectionalParticleWidth={1.5}
        onNodeClick={(n: GNode) => { if (n.type === "note" && n.id) onOpen(String(n.id)); }}
      />
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function MemoryPage() {
  const [tab, setTab] = useState<"manage" | "graph">("manage");
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2"><BrainCircuit className="w-5 h-5" /> Memory</h1>
          <p className="text-sm text-muted-foreground">Agent knowledge vault — markdown notes cross-linked into a graph.</p>
        </div>
        <div className="flex rounded-lg border border-border p-0.5">
          <button onClick={() => setTab("manage")}
            className={cn("px-3 py-1.5 text-sm rounded-md flex items-center gap-1.5", tab === "manage" ? "bg-primary text-primary-foreground" : "text-muted-foreground")}>
            <FolderOpen className="w-4 h-4" /> Manage
          </button>
          <button onClick={() => setTab("graph")}
            className={cn("px-3 py-1.5 text-sm rounded-md flex items-center gap-1.5", tab === "graph" ? "bg-primary text-primary-foreground" : "text-muted-foreground")}>
            <Network className="w-4 h-4" /> Graph
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {tab === "manage" ? <ManageView onOpen={setOpenId} /> : <GraphView onOpen={setOpenId} />}
      </div>

      {openId && <NoteModal noteId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
