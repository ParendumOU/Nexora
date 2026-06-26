"use client";

import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import {
  X, Loader2, Github, GitMerge, Search, User, Building2, Folder, Lock, Globe, Check, Plus,
} from "lucide-react";
import toast from "react-hot-toast";

import { gitProxyApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type GitCredential = { id: string; name: string; provider: string; color?: string };
type Namespace = { id: string; name: string; kind: "user" | "org" | "group" };
type CreatedRepo = { repo_url: string; provider: string; default_branch: string };

const KIND_ICON = { user: User, org: Building2, group: Folder } as const;

interface Props {
  open: boolean;
  credential: GitCredential | null;
  onClose: () => void;
  onCreated: (repo: CreatedRepo) => void;
}

export default function RepoCreateDialog({ open, credential, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [ns, setNs] = useState<string | null>(null);   // selected namespace id (null = none yet)
  const [isPrivate, setIsPrivate] = useState(true);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);

  const { data: namespaces = [], isLoading, isError, refetch } = useQuery<Namespace[]>({
    queryKey: ["git-namespaces", credential?.id],
    queryFn: () => gitProxyApi.namespaces(credential!.id).then((r) => r.data),
    enabled: open && !!credential,
  });

  // Default the selection to the personal namespace once loaded.
  const effectiveNs = ns ?? (namespaces.length ? namespaces[0].id : null);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? namespaces.filter((n) => n.name.toLowerCase().includes(q)) : namespaces;
  }, [namespaces, filter]);

  const reset = () => { setName(""); setNs(null); setIsPrivate(true); setFilter(""); };
  const handleOpenChange = (o: boolean) => { if (!o) { onClose(); reset(); } };

  const handleCreate = async () => {
    if (!credential) return;
    if (!name.trim()) { toast.error("Enter a repository name"); return; }
    setCreating(true);
    try {
      const { data } = await gitProxyApi.createRepo({
        credential_id: credential.id, name: name.trim(),
        namespace: effectiveNs ?? "", private: isPrivate,
      });
      toast.success(`Created ${data.repo_url}`);
      onCreated(data);
      onClose();
      reset();
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg ? `Create failed: ${msg}` : "Failed to create repository");
    } finally {
      setCreating(false);
    }
  };

  const ProviderIcon = credential?.provider === "github" ? Github : GitMerge;

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg max-h-[85vh] bg-card border border-border rounded-2xl shadow-2xl flex flex-col">

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
            <div className="flex items-center gap-2.5">
              <ProviderIcon className="w-4 h-4 text-muted-foreground" />
              <div>
                <Dialog.Title className="text-sm font-semibold">Create repository</Dialog.Title>
                {credential && (
                  <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5">
                    {credential.color && <span className="w-2 h-2 rounded-full inline-block" style={{ background: credential.color }} />}
                    {credential.name} · {credential.provider}
                  </p>
                )}
              </div>
            </div>
            <button onClick={onClose} className="p-1 rounded hover:bg-accent text-muted-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0 space-y-4">
            {/* Name */}
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Repository name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} autoFocus
                placeholder="my-new-repo"
                className="w-full h-9 text-sm border border-border rounded-md bg-background px-3 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>

            {/* Destination namespace — the part the user wanted as a proper picker */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs text-muted-foreground">Where to create it</label>
                {namespaces.length > 6 && (
                  <div className="relative">
                    <Search className="w-3 h-3 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground/60" />
                    <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="filter…"
                      className="h-7 w-36 text-xs border border-border rounded-md bg-background pl-6 pr-2 focus:outline-none focus:ring-1 focus:ring-ring" />
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-border max-h-56 overflow-y-auto divide-y divide-border/60">
                {isLoading ? (
                  <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading namespaces…
                  </div>
                ) : isError ? (
                  <div className="flex flex-col items-center gap-2 py-8 text-xs text-muted-foreground">
                    Could not load namespaces.
                    <Button size="sm" variant="outline" onClick={() => refetch()}>Retry</Button>
                  </div>
                ) : filtered.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-8">No matching namespaces</p>
                ) : (
                  filtered.map((n) => {
                    const Icon = KIND_ICON[n.kind] ?? Folder;
                    const selected = effectiveNs === n.id;
                    return (
                      <button key={n.id || "personal"} onClick={() => setNs(n.id)}
                        className={cn("w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-accent/50",
                          selected && "bg-primary/10 hover:bg-primary/15")}>
                        <Icon className={cn("w-4 h-4 shrink-0", selected ? "text-primary" : "text-muted-foreground/70")} />
                        <span className="text-sm flex-1 truncate">{n.name}</span>
                        <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">{n.kind}</span>
                        {selected && <Check className="w-4 h-4 text-primary shrink-0" />}
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            {/* Visibility */}
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Visibility</label>
              <div className="flex gap-1.5">
                {[{ v: false, label: "Public", Icon: Globe }, { v: true, label: "Private", Icon: Lock }].map(({ v, label, Icon }) => (
                  <button key={label} onClick={() => setIsPrivate(v)}
                    className={cn("flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border flex-1 justify-center transition-colors",
                      isPrivate === v ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-accent")}>
                    <Icon className="w-3 h-3" />{label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-border shrink-0 bg-accent/20">
            <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button size="sm" onClick={handleCreate} disabled={creating || !name.trim() || !credential}>
              {creating ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />Creating…</>
                : <><Plus className="w-3.5 h-3.5 mr-1.5" />Create &amp; link</>}
            </Button>
          </div>

        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
