"use client";
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { permissionsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Plus, Trash2, Users, ShieldCheck, Layers, Pencil, X } from "lucide-react";
import toast from "react-hot-toast";

interface GroupLimits {
  token_budget?: number;
  token_window_hours?: number;
  max_concurrent_agents?: number;
  max_provider_accounts?: number;
}

interface GroupCapabilities {
  agent_ids?: string[];
  skill_keys?: string[];
  tool_keys?: string[];
  persona_ids?: string[];
  provider_ids?: string[];
  chain_ids?: string[];
  default_chain_id?: string | null;
}

interface PermGroup {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
  member_ids: string[];
  member_count: number;
  limits?: GroupLimits;
  capabilities?: GroupCapabilities;
}

interface CatalogEntry {
  key: string;
  label: string;
  area: string;
  action: string;
}

interface AssignableResources {
  agents: { id: string; name: string }[];
  skills: { key: string; name: string }[];
  tools: { key: string; name: string }[];
  personas: { id: string; name: string }[];
  providers: { id: string; name: string; type: string }[];
  chains: { id: string; name: string }[];
}

interface FormLimits {
  token_budget: number;
  token_window_hours: number;
  max_concurrent_agents: number;
  max_provider_accounts: number;
}

interface FormCapabilities {
  agent_ids: Set<string>;
  skill_keys: Set<string>;
  tool_keys: Set<string>;
  persona_ids: Set<string>;
  provider_ids: Set<string>;
  chain_ids: Set<string>;
  default_chain_id: string | null;
}

type CapListDim = keyof Omit<FormCapabilities, "default_chain_id">;

interface FormState {
  name: string;
  description: string;
  permissions: Set<string>;
  memberIds: Set<string>;
  limits: FormLimits;
  capabilities: FormCapabilities;
}

const EMPTY_LIMITS: FormLimits = {
  token_budget: 0,
  token_window_hours: 0,
  max_concurrent_agents: 0,
  max_provider_accounts: 0,
};

function emptyCapabilities(): FormCapabilities {
  return {
    agent_ids: new Set(),
    skill_keys: new Set(),
    tool_keys: new Set(),
    persona_ids: new Set(),
    provider_ids: new Set(),
    chain_ids: new Set(),
    default_chain_id: null,
  };
}

export interface GroupMemberOption {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
}

function errDetail(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export function GroupsTab({ members }: { members: GroupMemberOption[] }) {
  const qc = useQueryClient();
  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<FormState>({
    name: "", description: "", permissions: new Set(), memberIds: new Set(),
    limits: { ...EMPTY_LIMITS }, capabilities: emptyCapabilities(),
  });
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const { data: groups = [], isLoading } = useQuery<PermGroup[]>({
    queryKey: ["perm-groups"],
    queryFn: () => permissionsApi.listGroups().then((r) => r.data),
  });

  const { data: catalog = [] } = useQuery<CatalogEntry[]>({
    queryKey: ["perm-catalog"],
    queryFn: () => permissionsApi.catalog().then((r) => r.data),
  });

  const { data: assignable } = useQuery<AssignableResources>({
    queryKey: ["perm-assignable"],
    queryFn: () => permissionsApi.assignable().then((r) => r.data),
  });

  // Area rows for the matrix: [{ area, label, viewKey, manageKey }]
  const areas = useMemo(() => {
    const byArea = new Map<string, { area: string; label: string; viewKey?: string; manageKey?: string }>();
    for (const entry of catalog) {
      if (entry.area === "ui") continue;
      const row = byArea.get(entry.area) ?? {
        area: entry.area,
        label: entry.label.split(" — ")[0],
        viewKey: undefined,
        manageKey: undefined,
      };
      if (entry.action === "view") row.viewKey = entry.key;
      if (entry.action === "manage") row.manageKey = entry.key;
      byArea.set(entry.area, row);
    }
    return Array.from(byArea.values());
  }, [catalog]);

  // Only members/viewers are restrictable; owners/admins always bypass groups.
  const assignableMembers = useMemo(
    () => members.filter((m) => m.role === "member" || m.role === "viewer"),
    [members]
  );

  function openEditor(group: PermGroup | null) {
    if (group) {
      setEditingId(group.id);
      setForm({
        name: group.name,
        description: group.description ?? "",
        permissions: new Set(group.permissions),
        memberIds: new Set(group.member_ids),
        limits: {
          token_budget: group.limits?.token_budget ?? 0,
          token_window_hours: group.limits?.token_window_hours ?? 0,
          max_concurrent_agents: group.limits?.max_concurrent_agents ?? 0,
          max_provider_accounts: group.limits?.max_provider_accounts ?? 0,
        },
        capabilities: {
          agent_ids: new Set(group.capabilities?.agent_ids ?? []),
          skill_keys: new Set(group.capabilities?.skill_keys ?? []),
          tool_keys: new Set(group.capabilities?.tool_keys ?? []),
          persona_ids: new Set(group.capabilities?.persona_ids ?? []),
          provider_ids: new Set(group.capabilities?.provider_ids ?? []),
          chain_ids: new Set(group.capabilities?.chain_ids ?? []),
          default_chain_id: group.capabilities?.default_chain_id ?? null,
        },
      });
    } else {
      setEditingId("new");
      setForm({
        name: "", description: "", permissions: new Set(), memberIds: new Set(),
        limits: { ...EMPTY_LIMITS }, capabilities: emptyCapabilities(),
      });
    }
  }

  function closeEditor() {
    setEditingId(null);
  }

  function togglePermission(key: string | undefined, impliedView?: string) {
    if (!key) return;
    setForm((f) => {
      const next = new Set(f.permissions);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
        // Granting manage implies view (mirrors the backend normalisation).
        if (impliedView) next.add(impliedView);
      }
      return { ...f, permissions: next };
    });
  }

  function toggleMember(userId: string) {
    setForm((f) => {
      const next = new Set(f.memberIds);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return { ...f, memberIds: next };
    });
  }

  function toggleCapability(dim: CapListDim, value: string) {
    setForm((f) => {
      const next = new Set(f.capabilities[dim]);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...f, capabilities: { ...f.capabilities, [dim]: next } };
    });
  }

  function setLimit(key: keyof FormLimits, raw: string) {
    const value = Math.max(0, Math.trunc(Number(raw) || 0));
    setForm((f) => ({ ...f, limits: { ...f.limits, [key]: value } }));
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        permissions: Array.from(form.permissions),
        limits: { ...form.limits },
        capabilities: {
          agent_ids: Array.from(form.capabilities.agent_ids),
          skill_keys: Array.from(form.capabilities.skill_keys),
          tool_keys: Array.from(form.capabilities.tool_keys),
          persona_ids: Array.from(form.capabilities.persona_ids),
          provider_ids: Array.from(form.capabilities.provider_ids),
          chain_ids: Array.from(form.capabilities.chain_ids),
          default_chain_id: form.capabilities.default_chain_id,
        },
      };
      const memberIds = Array.from(form.memberIds);
      if (editingId === "new") {
        const created = await permissionsApi.createGroup(payload).then((r) => r.data);
        await permissionsApi.setGroupMembers(created.id, memberIds);
      } else if (editingId) {
        await permissionsApi.updateGroup(editingId, payload);
        await permissionsApi.setGroupMembers(editingId, memberIds);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["perm-groups"] });
      toast.success(editingId === "new" ? "Group created" : "Group updated");
      closeEditor();
    },
    onError: (err: unknown) => toast.error(errDetail(err, "Failed to save group")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => permissionsApi.deleteGroup(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["perm-groups"] });
      setConfirmDeleteId(null);
      toast.success("Group deleted");
    },
    onError: (err: unknown) => toast.error(errDetail(err, "Failed to delete group")),
  });

  const uiAdvancedKey = "ui.advanced_mode";

  const limitFields: { key: keyof FormLimits; label: string }[] = [
    { key: "token_budget", label: "Token budget" },
    { key: "token_window_hours", label: "Budget window (hours, 0 = total/lifetime)" },
    { key: "max_concurrent_agents", label: "Max concurrent agents" },
    { key: "max_provider_accounts", label: "Max provider accounts" },
  ];

  const capSections: { dim: CapListDim; label: string; items: { value: string; label: string }[] }[] = [
    { dim: "agent_ids", label: "Agents", items: (assignable?.agents ?? []).map((a) => ({ value: a.id, label: a.name })) },
    { dim: "skill_keys", label: "Skills", items: (assignable?.skills ?? []).map((s) => ({ value: s.key, label: s.name })) },
    { dim: "tool_keys", label: "Tools", items: (assignable?.tools ?? []).map((t) => ({ value: t.key, label: t.name })) },
    { dim: "persona_ids", label: "Personas", items: (assignable?.personas ?? []).map((p) => ({ value: p.id, label: p.name })) },
    { dim: "provider_ids", label: "Providers", items: (assignable?.providers ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.type})` })) },
    { dim: "chain_ids", label: "Chains", items: (assignable?.chains ?? []).map((c) => ({ value: c.id, label: c.name })) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Groups restrict what members and viewers can see and do. A user in one or more groups
          only gets the permissions those groups grant; users without a group keep full member
          access. Owners and admins always have full access.
        </p>
        {editingId === null && (
          <button
            onClick={() => openEditor(null)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />
            New group
          </button>
        )}
      </div>

      {/* Group list */}
      {editingId === null && (
        <div className="space-y-2">
          {isLoading && <p className="text-xs text-muted-foreground py-4 text-center">Loading…</p>}
          {!isLoading && groups.length === 0 && (
            <div className="text-center py-10 rounded-xl border border-dashed border-border">
              <ShieldCheck className="w-6 h-6 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">No permission groups yet.</p>
              <p className="text-xs text-muted-foreground mt-1">
                Create one to limit what specific users can access.
              </p>
            </div>
          )}
          {groups.map((g) => (
            <div key={g.id} className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card">
              <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center shrink-0">
                <Layers className="w-4 h-4 text-muted-foreground" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{g.name}</div>
                <div className="text-[11px] text-muted-foreground truncate">
                  {g.permissions.length} permission{g.permissions.length !== 1 ? "s" : ""}
                  {g.description ? ` · ${g.description}` : ""}
                </div>
              </div>
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground shrink-0">
                <Users className="w-3 h-3" />
                {g.member_count}
              </span>
              <button
                onClick={() => openEditor(g)}
                className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                title="Edit group"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
              {confirmDeleteId === g.id ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => deleteMutation.mutate(g.id)}
                    disabled={deleteMutation.isPending}
                    className="px-2 py-1 rounded bg-destructive text-destructive-foreground text-[11px] font-medium hover:bg-destructive/90 disabled:opacity-50"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => setConfirmDeleteId(null)}
                    className="px-2 py-1 rounded border border-border text-[11px] hover:bg-accent"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDeleteId(g.id)}
                  className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors"
                  title="Delete group"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Editor */}
      {editingId !== null && (
        <div className="space-y-5 p-4 rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              {editingId === "new" ? "New group" : "Edit group"}
            </h3>
            <button onClick={closeEditor} className="p-1 rounded hover:bg-accent text-muted-foreground">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1.5">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Support team"
                className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5">Description (optional)</label>
              <input
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="What this group is for"
                className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>

          {/* Permission matrix */}
          <div>
            <label className="block text-xs font-medium mb-2">Permissions</label>
            <div className="rounded-lg border border-border overflow-hidden">
              <div className="grid grid-cols-[1fr_64px_72px] items-center px-3 py-1.5 bg-accent/40 text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                <span>Section</span>
                <span className="text-center">View</span>
                <span className="text-center">Manage</span>
              </div>
              <div className="divide-y divide-border max-h-72 overflow-y-auto">
                {areas.map((a) => {
                  const manageChecked = !!a.manageKey && form.permissions.has(a.manageKey);
                  const viewChecked = (!!a.viewKey && form.permissions.has(a.viewKey)) || manageChecked;
                  return (
                    <div key={a.area} className="grid grid-cols-[1fr_64px_72px] items-center px-3 py-1.5 bg-card">
                      <span className="text-xs truncate">{a.label}</span>
                      <span className="text-center">
                        <input
                          type="checkbox"
                          checked={viewChecked}
                          disabled={manageChecked}
                          onChange={() => togglePermission(a.viewKey)}
                          className="accent-primary"
                        />
                      </span>
                      <span className="text-center">
                        <input
                          type="checkbox"
                          checked={manageChecked}
                          onChange={() => togglePermission(a.manageKey, a.viewKey)}
                          className="accent-primary"
                        />
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
            <label className="flex items-center gap-2 mt-3 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={form.permissions.has(uiAdvancedKey)}
                onChange={() => togglePermission(uiAdvancedKey)}
                className="accent-primary"
              />
              <span className="font-medium">Allow advanced UI mode</span>
              <span className="text-muted-foreground">— unchecked forces the simple interface</span>
            </label>
          </div>

          {/* Usage limits */}
          <div>
            <label className="block text-xs font-medium mb-2">Usage limits</label>
            <div className="rounded-lg border border-border p-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
              {limitFields.map((lf) => (
                <div key={lf.key}>
                  <label className="block text-[11px] text-muted-foreground mb-1">{lf.label}</label>
                  <input
                    type="number"
                    min={0}
                    value={form.limits[lf.key]}
                    onChange={(e) => setLimit(lf.key, e.target.value)}
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1.5">0 = unlimited</p>
          </div>

          {/* Capabilities */}
          <div>
            <label className="block text-xs font-medium mb-2">Capabilities</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
              {capSections.map((sec) => (
                <div key={sec.dim}>
                  <div className="text-[11px] font-medium text-muted-foreground mb-1">
                    {sec.label} ({form.capabilities[sec.dim].size})
                  </div>
                  {sec.items.length === 0 ? (
                    <p className="text-[10px] text-muted-foreground">None available.</p>
                  ) : (
                    <div className="rounded-lg border border-border divide-y divide-border max-h-40 overflow-y-auto">
                      {sec.items.map((it) => (
                        <label
                          key={it.value}
                          className="flex items-center gap-3 px-3 py-1.5 bg-card cursor-pointer hover:bg-accent/40"
                        >
                          <input
                            type="checkbox"
                            checked={form.capabilities[sec.dim].has(it.value)}
                            onChange={() => toggleCapability(sec.dim, it.value)}
                            className="accent-primary"
                          />
                          <span className="text-xs truncate flex-1">{it.label}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground mb-1">Forced default chain</label>
                <select
                  value={form.capabilities.default_chain_id ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      capabilities: { ...f.capabilities, default_chain_id: e.target.value || null },
                    }))
                  }
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">None</option>
                  {(assignable?.chains ?? []).map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground mt-1.5">Leave a list empty to allow all.</p>
          </div>

          {/* Members */}
          <div>
            <label className="block text-xs font-medium mb-2">
              Assigned users ({form.memberIds.size})
            </label>
            {assignableMembers.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No members or viewers to assign. Owners and admins cannot be restricted.
              </p>
            ) : (
              <div className="rounded-lg border border-border divide-y divide-border max-h-56 overflow-y-auto">
                {assignableMembers.map((m) => (
                  <label
                    key={m.user_id}
                    className="flex items-center gap-3 px-3 py-2 bg-card cursor-pointer hover:bg-accent/40"
                  >
                    <input
                      type="checkbox"
                      checked={form.memberIds.has(m.user_id)}
                      onChange={() => toggleMember(m.user_id)}
                      className="accent-primary"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium truncate">{m.full_name}</div>
                      <div className="text-[10px] text-muted-foreground truncate">{m.email}</div>
                    </div>
                    <span className="text-[10px] text-muted-foreground shrink-0">{m.role}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!form.name.trim() || saveMutation.isPending}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving…" : editingId === "new" ? "Create group" : "Save changes"}
            </button>
            <button
              onClick={closeEditor}
              className="px-4 py-2 rounded-lg border border-border text-sm hover:bg-accent transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
