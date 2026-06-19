"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { profileFactsApi, ProfileFact } from "@/lib/api";
import { Loader2, Plus, Trash2, Save, Pencil, X } from "lucide-react";
import toast from "react-hot-toast";

// Structured keyed facts the AI records via `remember_user` (op=upsert). Editing one
// fact never wipes the others — the whole point of the patch-based profile store.
// The reserved `freeform` key is the free-text notes blob, edited elsewhere, so hide it.
export function ProfileFactsEditor() {
  const qc = useQueryClient();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  const { data: facts = [], isLoading } = useQuery({
    queryKey: ["profile-facts"],
    queryFn: async () => (await profileFactsApi.list()).data,
  });
  const visible = facts.filter((f) => f.key !== "freeform");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["profile-facts"] });

  const upsert = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => profileFactsApi.upsert(key, value),
    onSuccess: () => { invalidate(); toast.success("Saved"); },
    onError: () => toast.error("Save failed"),
  });
  const del = useMutation({
    mutationFn: (key: string) => profileFactsApi.delete(key),
    onSuccess: () => { invalidate(); toast.success("Removed"); },
    onError: () => toast.error("Delete failed"),
  });

  const startEdit = (f: ProfileFact) => { setEditingKey(f.key); setDraftValue(f.value); };
  const saveEdit = (key: string) => {
    if (!draftValue.trim()) return;
    upsert.mutate({ key, value: draftValue.trim() });
    setEditingKey(null);
  };
  const addFact = () => {
    const k = newKey.trim(), v = newValue.trim();
    if (!k || !v) { toast.error("Key and value required"); return; }
    upsert.mutate({ key: k, value: v });
    setNewKey(""); setNewValue("");
  };

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold">Structured facts</h3>
        <p className="text-xs text-muted-foreground">
          Discrete facts the AI keeps about you (role, timezone, current projects…). Each is patched independently.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
      ) : visible.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">No structured facts yet.</p>
      ) : (
        <div className="space-y-1.5">
          {visible.map((f) => (
            <div key={f.id} className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5">
              <span className="font-mono text-xs text-primary shrink-0 min-w-[110px] pt-1">{f.key}</span>
              {editingKey === f.key ? (
                <input
                  autoFocus
                  value={draftValue}
                  onChange={(e) => setDraftValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveEdit(f.key); if (e.key === "Escape") setEditingKey(null); }}
                  className="flex-1 bg-input border border-border rounded px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-ring"
                />
              ) : (
                <span className="flex-1 text-sm break-words pt-1">{f.value}</span>
              )}
              <div className="flex items-center gap-0.5 shrink-0">
                {editingKey === f.key ? (
                  <>
                    <button onClick={() => saveEdit(f.key)} className="p-1 hover:bg-accent rounded"><Save className="w-3.5 h-3.5" /></button>
                    <button onClick={() => setEditingKey(null)} className="p-1 hover:bg-accent rounded"><X className="w-3.5 h-3.5" /></button>
                  </>
                ) : (
                  <>
                    <button onClick={() => startEdit(f)} className="p-1 hover:bg-accent rounded"><Pencil className="w-3.5 h-3.5" /></button>
                    <button onClick={() => del.mutate(f.key)} className="p-1 hover:bg-accent rounded"><Trash2 className="w-3.5 h-3.5 text-red-500" /></button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="key (e.g. role)"
          className="w-36 bg-input border border-border rounded px-2 py-1 text-sm font-mono outline-none focus:ring-1 focus:ring-ring"
        />
        <input
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") addFact(); }}
          placeholder="value"
          className="flex-1 bg-input border border-border rounded px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <button onClick={addFact} disabled={upsert.isPending} className="flex items-center gap-1 px-2.5 py-1 text-sm border border-border rounded-md hover:bg-accent">
          <Plus className="w-3.5 h-3.5" /> Add
        </button>
      </div>
    </div>
  );
}
