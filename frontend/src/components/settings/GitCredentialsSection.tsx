"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { gitCredentialsApi } from "@/lib/api";
import toast from "react-hot-toast";
import {
  Plus, Loader2, Trash2, Eye, EyeOff, Github, GitMerge, Download, Pencil, Check, X,
} from "lucide-react";

type GitCredential = {
  id: string;
  name: string;
  provider: string;
  color: string;
  base_url: string | null;
  token_hint: string;
  created_at: string;
};

const PRESET_COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ec4899", "#3b82f6", "#8b5cf6", "#14b8a6"];

const EMPTY_FORM = { name: "", provider: "github", token: "", color: PRESET_COLORS[0], base_url: "" };

interface GitCredentialsSectionProps {
  onImport: (cred: GitCredential) => void;
}

export default function GitCredentialsSection({ onImport }: GitCredentialsSectionProps) {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ name: string; color: string; token: string; base_url: string }>({ name: "", color: "", token: "", base_url: "" });
  const [showEditToken, setShowEditToken] = useState(false);

  const { data: creds = [], isLoading } = useQuery<GitCredential[]>({
    queryKey: ["git-credentials"],
    queryFn: () => gitCredentialsApi.list().then((r) => r.data),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => gitCredentialsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["git-credentials"] }); toast.success("Credential removed"); },
    onError: () => toast.error("Failed to remove credential"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: object }) => gitCredentialsApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["git-credentials"] }); toast.success("Credential updated"); setEditingId(null); },
    onError: () => toast.error("Failed to update credential"),
  });

  const handleCreate = async () => {
    if (!form.name.trim() || !form.token.trim()) { toast.error("Name and token required"); return; }
    setSaving(true);
    try {
      await gitCredentialsApi.create({
        name: form.name.trim(),
        provider: form.provider,
        token: form.token.trim(),
        color: form.color,
        base_url: form.base_url.trim() || undefined,
      });
      qc.invalidateQueries({ queryKey: ["git-credentials"] });
      toast.success("Credential added");
      setForm(EMPTY_FORM);
      setShowForm(false);
    } catch {
      toast.error("Failed to save credential");
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (c: GitCredential) => {
    setEditingId(c.id);
    setEditForm({ name: c.name, color: c.color, token: "", base_url: c.base_url || "" });
    setShowEditToken(false);
  };

  const saveEdit = () => {
    if (!editingId || !editForm.name.trim()) return;
    const data: Record<string, string> = { name: editForm.name.trim(), color: editForm.color, base_url: editForm.base_url.trim() };
    if (editForm.token.trim()) data.token = editForm.token.trim();
    updateMut.mutate({ id: editingId, data });
  };

  const ProviderIcon = ({ provider }: { provider: string }) =>
    provider === "github" ? <Github className="w-3.5 h-3.5" /> : <GitMerge className="w-3.5 h-3.5" />;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold">Source Control</h2>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
            Global GitHub / GitLab credentials. Assign to projects or use for bulk repository import.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button size="sm" variant="outline" onClick={() => { setShowForm(true); setForm(EMPTY_FORM); }} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />Add Credential
          </Button>
        </div>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="border border-border rounded-lg p-4 space-y-3 bg-card">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">New credential</p>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="My GitHub" className="h-8 text-xs" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Provider</label>
              <div className="flex gap-1">
                {["github", "gitlab"].map(p => (
                  <button key={p} onClick={() => setForm(f => ({ ...f, provider: p }))}
                    className={cn("flex-1 text-xs py-1.5 rounded border transition-colors capitalize",
                      form.provider === p ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}>
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Personal Access Token</label>
            <div className="relative">
              <Input
                type={showToken ? "text" : "password"}
                value={form.token}
                onChange={e => setForm(f => ({ ...f, token: e.target.value }))}
                placeholder={form.provider === "github" ? "ghp_…" : "glpat-…"}
                className="h-8 text-xs pr-8 font-mono"
              />
              <button onClick={() => setShowToken(s => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                {showToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
          {form.provider === "gitlab" && (
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Base URL <span className="text-muted-foreground/60">(self-hosted, leave blank for gitlab.com)</span></label>
              <Input value={form.base_url} onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))} placeholder="https://gitlab.example.com" className="h-8 text-xs" />
            </div>
          )}
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Color</label>
            <div className="flex gap-1.5">
              {PRESET_COLORS.map(c => (
                <button key={c} onClick={() => setForm(f => ({ ...f, color: c }))}
                  className={cn("w-5 h-5 rounded-full border-2 transition-all", form.color === c ? "border-foreground scale-110" : "border-transparent")}
                  style={{ background: c }} />
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={saving}>
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
            </Button>
          </div>
        </div>
      )}

      {/* Credentials list */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />Loading…
        </div>
      ) : creds.length === 0 && !showForm ? (
        <div className="flex flex-col items-center gap-3 py-10 border border-dashed border-border rounded-xl text-center max-w-xl">
          <GitMerge className="w-6 h-6 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium">No source control credentials</p>
            <p className="text-xs text-muted-foreground mt-0.5">Add a GitHub or GitLab PAT to import repositories</p>
          </div>
          <Button size="sm" onClick={() => setShowForm(true)}>Add first credential</Button>
        </div>
      ) : (
        <div className="space-y-1.5 max-w-xl">
          {creds.map(c => (
            <div key={c.id} className="flex items-center gap-3 px-3 py-2.5 bg-card border border-border rounded-lg hover:border-border/60 transition-colors">
              {editingId === c.id ? (
                <div className="flex-1 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Input value={editForm.name} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} className="h-7 text-xs" placeholder="Name" />
                    <div className="flex gap-1">
                      {PRESET_COLORS.map(col => (
                        <button key={col} onClick={() => setEditForm(f => ({ ...f, color: col }))}
                          className={cn("w-5 h-5 rounded-full border-2 transition-all", editForm.color === col ? "border-foreground scale-110" : "border-transparent")}
                          style={{ background: col }} />
                      ))}
                    </div>
                  </div>
                  <div className="relative">
                    <Input
                      type={showEditToken ? "text" : "password"}
                      value={editForm.token}
                      onChange={e => setEditForm(f => ({ ...f, token: e.target.value }))}
                      placeholder="New token (leave blank to keep)"
                      className="h-7 text-xs pr-8 font-mono"
                    />
                    <button onClick={() => setShowEditToken(s => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                      {showEditToken ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    </button>
                  </div>
                  {c.provider === "gitlab" && (
                    <Input value={editForm.base_url} onChange={e => setEditForm(f => ({ ...f, base_url: e.target.value }))} placeholder="Base URL" className="h-7 text-xs" />
                  )}
                  <div className="flex justify-end gap-1.5">
                    <button onClick={() => setEditingId(null)} className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-3.5 h-3.5" /></button>
                    <button onClick={saveEdit} className="p-1 rounded hover:bg-accent text-green-400"><Check className="w-3.5 h-3.5" /></button>
                  </div>
                </div>
              ) : (
                <>
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: c.color }} />
                  <ProviderIcon provider={c.provider} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{c.name}</p>
                    <p className="text-xs text-muted-foreground font-mono">
                      {c.token_hint}
                      {c.base_url && <span className="ml-2 not-mono text-muted-foreground/60">· {c.base_url}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => onImport(c)}
                      title="Import repositories"
                      className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-border hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                    >
                      <Download className="w-3 h-3" />Import repos
                    </button>
                    <button onClick={() => startEdit(c)} className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground">
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => deleteMut.mutate(c.id)} className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
