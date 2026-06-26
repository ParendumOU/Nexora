"use client";

import { useState, useCallback } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  X, Loader2, Github, GitMerge, ChevronRight, ChevronDown,
  User, Building2, Folder, FolderOpen, Lock, Globe, Check, Plus,
} from "lucide-react";
import toast from "react-hot-toast";

import { gitCredentialsApi, gitProxyApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type GitCredential = { id: string; name: string; provider: string; color?: string };
type CreatedRepo = { repo_url: string; provider: string; default_branch: string };

type Node = {
  id: string;
  type: "user" | "org" | "group" | "subgroup";
  name: string;
  full_path?: string;
  subgroups: Node[];
  children_loaded: boolean;
  loading?: boolean;
};

// Node id → the namespace value the create-repo API expects.
//   GitHub:  gh_org_{login} → login ;  gh_user_* → "" (personal)
//   GitLab:  gl_group_{id}  → id    ;  gl_user_* → "" (personal)
function nodeNamespace(id: string): string {
  if (id.startsWith("gh_org_")) return id.slice("gh_org_".length);
  if (id.startsWith("gl_group_")) return id.slice("gl_group_".length);
  return ""; // user/personal
}

function updateNode(nodes: Node[], id: string, fn: (n: Node) => Node): Node[] {
  return nodes.map((n) => {
    if (n.id === id) return fn(n);
    if (n.subgroups?.length) return { ...n, subgroups: updateNode(n.subgroups, id, fn) };
    return n;
  });
}

const KIND_ICON = { user: User, org: Building2, group: Folder, subgroup: Folder } as const;

interface Props {
  open: boolean;
  credential: GitCredential | null;
  onClose: () => void;
  onCreated: (repo: CreatedRepo) => void;
}

function NodeRow({ node, depth, selectedId, onSelect, onExpand }: {
  node: Node; depth: number; selectedId: string | null;
  onSelect: (n: Node) => void; onExpand: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon = expanded ? FolderOpen : (KIND_ICON[node.type] ?? Folder);
  const selected = selectedId === node.id;
  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !node.children_loaded && !node.loading) onExpand(node.id);
  };
  return (
    <div>
      <div className={cn("flex items-center gap-1.5 rounded-md pr-2 transition-colors hover:bg-accent/40",
        selected && "bg-primary/10 hover:bg-primary/15")} style={{ paddingLeft: depth * 14 }}>
        <button onClick={toggle} className="p-1 text-muted-foreground shrink-0" title="Expand subgroups">
          {node.loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </button>
        <button onClick={() => onSelect(node)} className="flex items-center gap-2 flex-1 py-2 text-left min-w-0">
          <Icon className={cn("w-4 h-4 shrink-0", selected ? "text-primary" : node.type === "user" ? "text-muted-foreground/70" : "text-yellow-500/70")} />
          <span className="text-sm truncate flex-1">{node.full_path || node.name}</span>
          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">{node.type}</span>
          {selected && <Check className="w-4 h-4 text-primary shrink-0" />}
        </button>
      </div>
      {expanded && node.children_loaded && (
        node.subgroups.length > 0 ? (
          node.subgroups.map((sg) => (
            <NodeRow key={sg.id} node={sg} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} onExpand={onExpand} />
          ))
        ) : (
          <p className="text-[11px] text-muted-foreground/50 py-1" style={{ paddingLeft: (depth + 1) * 14 + 8 }}>No subgroups</p>
        )
      )}
    </div>
  );
}

export default function RepoCreateDialog({ open, credential, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [isPrivate, setIsPrivate] = useState(true);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loadingRoot, setLoadingRoot] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Node | null>(null);
  const [creating, setCreating] = useState(false);

  const reset = () => { setName(""); setIsPrivate(true); setNodes([]); setLoaded(false); setSelected(null); };
  const handleOpenChange = (o: boolean) => { if (!o) { onClose(); reset(); } };

  const loadRoots = useCallback(async () => {
    if (!credential) return;
    setLoadingRoot(true);
    try {
      const res = await gitCredentialsApi.expand(credential.id);
      const roots: Node[] = (res.data?.subgroups || []).map((n: Node) => ({ ...n, subgroups: n.subgroups || [] }));
      setNodes(roots);
      setLoaded(true);
      // Default-select the personal namespace (first user node).
      const personal = roots.find((n) => n.type === "user") ?? roots[0] ?? null;
      setSelected(personal);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Failed to load namespaces");
    } finally {
      setLoadingRoot(false);
    }
  }, [credential]);

  const handleExpand = useCallback(async (nodeId: string) => {
    if (!credential) return;
    setNodes((prev) => updateNode(prev, nodeId, (n) => ({ ...n, loading: true })));
    try {
      const res = await gitCredentialsApi.expand(credential.id, nodeId);
      const subgroups: Node[] = (res.data?.subgroups || []).map((n: Node) => ({ ...n, subgroups: n.subgroups || [] }));
      setNodes((prev) => updateNode(prev, nodeId, (n) => ({ ...n, subgroups, children_loaded: true, loading: false })));
    } catch {
      setNodes((prev) => updateNode(prev, nodeId, (n) => ({ ...n, loading: false })));
      toast.error("Failed to load subgroups");
    }
  }, [credential]);

  const handleCreate = async () => {
    if (!credential) return;
    if (!name.trim()) { toast.error("Enter a repository name"); return; }
    if (!selected) { toast.error("Pick where to create it"); return; }
    setCreating(true);
    try {
      const { data } = await gitProxyApi.createRepo({
        credential_id: credential.id, name: name.trim(),
        namespace: nodeNamespace(selected.id), private: isPrivate,
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
            <button onClick={onClose} className="p-1 rounded hover:bg-accent text-muted-foreground"><X className="w-4 h-4" /></button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0 space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Repository name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="my-new-repo"
                className="w-full h-9 text-sm border border-border rounded-md bg-background px-3 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs text-muted-foreground">Where to create it</label>
                {selected && <span className="text-[11px] text-muted-foreground truncate max-w-[55%]">→ {selected.full_path || selected.name}</span>}
              </div>
              <div className="rounded-lg border border-border max-h-64 overflow-y-auto p-1">
                {!loaded ? (
                  <div className="flex flex-col items-center gap-3 py-8">
                    <p className="text-xs text-muted-foreground">Load your accounts, organizations and groups, then expand to find subgroups.</p>
                    <Button size="sm" onClick={loadRoots} disabled={loadingRoot}>
                      {loadingRoot ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />Loading…</> : "Load namespaces"}
                    </Button>
                  </div>
                ) : nodes.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-8">No namespaces found for this token</p>
                ) : (
                  nodes.map((n) => (
                    <NodeRow key={n.id} node={n} depth={0} selectedId={selected?.id ?? null} onSelect={setSelected} onExpand={handleExpand} />
                  ))
                )}
              </div>
            </div>

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
            <Button size="sm" onClick={handleCreate} disabled={creating || !name.trim() || !selected || !credential}>
              {creating ? <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />Creating…</> : <><Plus className="w-3.5 h-3.5 mr-1.5" />Create &amp; link</>}
            </Button>
          </div>

        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
