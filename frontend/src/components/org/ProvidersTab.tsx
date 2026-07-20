"use client";
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { orgsApi, providersApi, type ProviderAssignment } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Boxes,
  KeyRound,
  ChevronDown,
  ChevronRight,
  Search,
  AlertTriangle,
  Plus,
  X,
} from "lucide-react";
import toast from "react-hot-toast";

type ProviderMode = "all" | "own" | "assigned";

export interface ProviderMemberOption {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  provider_mode?: ProviderMode;
  assigned_provider_count?: number;
}

const MODES: { value: ProviderMode; label: string; description: string }[] = [
  {
    value: "all",
    label: "All accounts",
    description: "Every unassigned account in the org, plus any reserved to them.",
  },
  {
    value: "own",
    label: "Own accounts",
    description: "Only accounts they added themselves, plus any reserved to them.",
  },
  {
    value: "assigned",
    label: "Assigned only",
    description: "Only accounts an admin reserved to them. Blocked if none are assigned.",
  },
];

function errDetail(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export function ProvidersTab({
  members,
  orgId,
}: {
  members: ProviderMemberOption[];
  orgId: string;
}) {
  const qc = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [assignSearch, setAssignSearch] = useState("");
  const [assignPicks, setAssignPicks] = useState<Set<string>>(new Set());

  const { data: assignments = [], isLoading } = useQuery<ProviderAssignment[]>({
    queryKey: ["provider-assignments", orgId],
    queryFn: () => providersApi.getProviderAssignments().then((r) => r.data),
  });

  const byMember = useMemo(() => {
    const map = new Map<string, ProviderAssignment[]>();
    for (const a of assignments) {
      if (!a.assigned_user_id) continue;
      const list = map.get(a.assigned_user_id) ?? [];
      list.push(a);
      map.set(a.assigned_user_id, list);
    }
    return map;
  }, [assignments]);

  const unassigned = useMemo(
    () => assignments.filter((a) => !a.assigned_user_id),
    [assignments],
  );

  const modeMutation = useMutation({
    mutationFn: ({ userId, mode }: { userId: string; mode: ProviderMode }) =>
      orgsApi.setMemberProviderMode(orgId, userId, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["org-members", orgId] });
      toast.success("Provider access updated");
    },
    onError: (err: unknown) => toast.error(errDetail(err, "Failed to update provider access")),
  });

  const assignMutation = useMutation({
    mutationFn: ({ providerIds, userId }: { providerIds: string[]; userId: string | null }) =>
      Promise.all(providerIds.map((id) => providersApi.assignProvider(id, userId))),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-assignments", orgId] });
      qc.invalidateQueries({ queryKey: ["org-members", orgId] });
      setAssignPicks(new Set());
      setAssignSearch("");
    },
    onError: (err: unknown) => toast.error(errDetail(err, "Failed to assign account")),
  });

  const unassignMutation = useMutation({
    mutationFn: (providerId: string) => providersApi.assignProvider(providerId, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-assignments", orgId] });
      qc.invalidateQueries({ queryKey: ["org-members", orgId] });
    },
    onError: (err: unknown) => toast.error(errDetail(err, "Failed to return account to the pool")),
  });

  function toggleExpand(userId: string) {
    setExpandedId((prev) => (prev === userId ? null : userId));
    setAssignSearch("");
    setAssignPicks(new Set());
  }

  function togglePick(id: string) {
    setAssignPicks((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const filteredPool = useMemo(() => {
    const q = assignSearch.trim().toLowerCase();
    if (!q) return unassigned;
    return unassigned.filter(
      (a) =>
        a.name.toLowerCase().includes(q) || a.provider_type.toLowerCase().includes(q),
    );
  }, [unassigned, assignSearch]);

  const total = assignments.length;
  const reserved = total - unassigned.length;

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Control which provider accounts each member can use. Set a member&apos;s mode, then reserve
        specific accounts to them. A reserved account belongs to one member only and is removed from
        everyone else&apos;s pool.
      </p>

      {/* Shared pool summary */}
      <div className="flex items-center gap-3 p-3 rounded-xl border border-border bg-card">
        <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center shrink-0">
          <Boxes className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium">Shared pool</div>
          <div className="text-[11px] text-muted-foreground">
            {isLoading
              ? "Loading accounts…"
              : total === 0
                ? "No provider accounts in this organization yet."
                : `${unassigned.length} of ${total} account${total !== 1 ? "s" : ""} unassigned · ${reserved} reserved`}
          </div>
        </div>
      </div>

      {total === 0 && !isLoading && (
        <div className="text-center py-8 rounded-xl border border-dashed border-border">
          <KeyRound className="w-6 h-6 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">No provider accounts to govern.</p>
          <p className="text-xs text-muted-foreground mt-1">
            Add provider accounts under Providers, then reserve them to members here.
          </p>
        </div>
      )}

      {/* Mode legend */}
      <div className="rounded-lg border border-border bg-card/50 p-3 space-y-1">
        {MODES.map((m) => (
          <div key={m.value} className="flex gap-2 text-[11px]">
            <span className="font-medium text-foreground shrink-0 w-24">{m.label}</span>
            <span className="text-muted-foreground">{m.description}</span>
          </div>
        ))}
      </div>

      {/* Members */}
      <div className="space-y-2">
        {members.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-8">No members yet.</p>
        )}
        {members.map((m) => {
          const mode: ProviderMode = m.provider_mode ?? "all";
          const memberAccounts = byMember.get(m.user_id) ?? [];
          const count = m.assigned_provider_count ?? memberAccounts.length;
          const isExpanded = expandedId === m.user_id;
          const blocked = mode === "assigned" && count === 0;

          return (
            <div key={m.user_id} className="rounded-xl border border-border bg-card overflow-hidden">
              <div className="flex items-center gap-3 p-3">
                <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-sm font-bold shrink-0">
                  {m.full_name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate flex items-center gap-1.5">
                    {m.full_name}
                    <span
                      className={cn(
                        "text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0",
                        m.role === "owner"
                          ? "bg-primary/10 text-primary"
                          : m.role === "admin"
                            ? "bg-amber-500/10 text-amber-500"
                            : m.role === "member"
                              ? "bg-accent text-muted-foreground"
                              : "bg-muted/60 text-muted-foreground/70",
                      )}
                    >
                      {m.role}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">{m.email}</div>
                </div>

                {blocked && (
                  <span
                    className="flex items-center gap-1 text-[10px] text-destructive"
                    title="Assigned-only mode with no accounts reserved — this member cannot run the AI."
                  >
                    <AlertTriangle className="w-3.5 h-3.5" />
                  </span>
                )}

                <select
                  value={mode}
                  disabled={modeMutation.isPending}
                  onChange={(e) =>
                    modeMutation.mutate({ userId: m.user_id, mode: e.target.value as ProviderMode })
                  }
                  className="text-xs bg-background border border-border rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                >
                  {MODES.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>

                <button
                  onClick={() => toggleExpand(m.user_id)}
                  className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-accent text-muted-foreground hover:bg-accent/80 transition-colors shrink-0"
                  title="Manage reserved accounts"
                >
                  <KeyRound className="w-3 h-3" />
                  {count}
                  {isExpanded ? (
                    <ChevronDown className="w-3 h-3" />
                  ) : (
                    <ChevronRight className="w-3 h-3" />
                  )}
                </button>
              </div>

              {isExpanded && (
                <div className="border-t border-border bg-background/40 p-3 space-y-4">
                  {/* Reserved accounts */}
                  <div>
                    <div className="text-[11px] font-medium text-muted-foreground mb-1.5">
                      Reserved to {m.full_name.split(" ")[0]} ({memberAccounts.length})
                    </div>
                    {memberAccounts.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground">No accounts reserved yet.</p>
                    ) : (
                      <div className="rounded-lg border border-border divide-y divide-border">
                        {memberAccounts.map((a) => (
                          <div
                            key={a.id}
                            className="flex items-center gap-2 px-3 py-1.5 bg-card"
                          >
                            <div className="flex-1 min-w-0">
                              <span className="text-xs truncate">{a.name}</span>
                              <span className="text-[10px] text-muted-foreground ml-1.5">
                                {a.provider_type}
                              </span>
                              {!a.is_active && (
                                <span className="text-[10px] text-muted-foreground/70 ml-1.5">
                                  (inactive)
                                </span>
                              )}
                            </div>
                            <button
                              onClick={() => unassignMutation.mutate(a.id)}
                              disabled={unassignMutation.isPending}
                              className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-destructive hover:border-destructive/40 transition-colors disabled:opacity-50"
                              title="Return to shared pool"
                            >
                              <X className="w-3 h-3" />
                              Unassign
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Assign from pool */}
                  <div>
                    <div className="text-[11px] font-medium text-muted-foreground mb-1.5">
                      Assign accounts from the shared pool
                    </div>
                    {unassigned.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground">
                        No unassigned accounts available.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        <div className="relative">
                          <Search className="w-3.5 h-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
                          <input
                            value={assignSearch}
                            onChange={(e) => setAssignSearch(e.target.value)}
                            placeholder="Search accounts…"
                            className="w-full text-xs bg-background border border-border rounded-lg pl-8 pr-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                          />
                        </div>
                        <div className="rounded-lg border border-border divide-y divide-border max-h-56 overflow-y-auto">
                          {filteredPool.length === 0 ? (
                            <p className="px-3 py-2 text-[11px] text-muted-foreground">
                              No matching accounts.
                            </p>
                          ) : (
                            filteredPool.map((a) => (
                              <label
                                key={a.id}
                                className="flex items-center gap-3 px-3 py-1.5 bg-card cursor-pointer hover:bg-accent/40"
                              >
                                <input
                                  type="checkbox"
                                  checked={assignPicks.has(a.id)}
                                  onChange={() => togglePick(a.id)}
                                  className="accent-primary"
                                />
                                <span className="text-xs truncate flex-1">{a.name}</span>
                                <span className="text-[10px] text-muted-foreground shrink-0">
                                  {a.provider_type}
                                </span>
                              </label>
                            ))
                          )}
                        </div>
                        <button
                          onClick={() =>
                            assignMutation.mutate({
                              providerIds: Array.from(assignPicks),
                              userId: m.user_id,
                            })
                          }
                          disabled={assignPicks.size === 0 || assignMutation.isPending}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                        >
                          <Plus className="w-3.5 h-3.5" />
                          {assignMutation.isPending
                            ? "Assigning…"
                            : `Assign ${assignPicks.size || ""} account${assignPicks.size === 1 ? "" : "s"}`.trim()}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
