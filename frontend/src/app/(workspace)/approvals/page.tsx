"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { approvalsApi } from "@/lib/api";
import { Loader2, ShieldCheck, CheckCircle, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

type Approval = {
  id: string;
  chat_id: string;
  agent_name: string | null;
  tool_name: string;
  tool_args: Record<string, unknown>;
  risk_tier: string;
  status: string;
  created_at: string;
  decided_at: string | null;
};

const STATUS: Record<string, { label: string; className: string; icon: React.FC<{ className?: string }> }> = {
  pending:  { label: "Pending",  className: "bg-yellow-400/15 text-yellow-400", icon: Clock },
  approved: { label: "Approved", className: "bg-green-400/15 text-green-400",   icon: CheckCircle },
  denied:   { label: "Denied",   className: "bg-red-400/15 text-red-400",       icon: XCircle },
};

const TIER_COLOR: Record<string, string> = {
  read: "bg-muted text-muted-foreground",
  write: "bg-blue-400/15 text-blue-400",
  external: "bg-orange-400/15 text-orange-400",
  exec: "bg-red-400/15 text-red-400",
};

const FILTERS = ["pending", "approved", "denied", "all"] as const;

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<typeof FILTERS[number]>("pending");

  const { data: approvals, isLoading } = useQuery<Approval[]>({
    queryKey: ["approvals", filter],
    queryFn: () => approvalsApi.list(filter).then((r) => r.data),
    refetchInterval: 8000,
  });

  const approve = useMutation({
    mutationFn: (id: string) => approvalsApi.approve(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
  const deny = useMutation({
    mutationFn: (id: string) => approvalsApi.deny(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-border flex items-center gap-3 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
          <ShieldCheck className="w-4 h-4 text-primary" />
        </div>
        <div>
          <h1 className="text-sm font-semibold">Approvals</h1>
          <p className="text-xs text-muted-foreground">Review tool actions held for human approval</p>
        </div>
      </div>

      <div className="px-6 pt-4 flex gap-1 shrink-0">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "px-3 py-1.5 text-xs rounded-md font-medium transition-colors",
              filter === f ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground hover:bg-accent"
            )}
          >
            {f === "all" ? "All" : STATUS[f]?.label ?? f}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {isLoading && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        )}

        {!isLoading && (!approvals || approvals.length === 0) && (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
            <ShieldCheck className="w-10 h-10 opacity-20" />
            <p className="text-sm">No approvals {filter !== "all" ? `with status "${filter}"` : "yet"}</p>
          </div>
        )}

        {approvals?.map((a) => {
          const cfg = STATUS[a.status] ?? STATUS.pending;
          const Icon = cfg.icon;
          const isPending = a.status === "pending";
          return (
            <div key={a.id} className="border border-border rounded-lg p-4 bg-card space-y-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide", cfg.className)}>
                  <Icon className="w-3 h-3 inline mr-1" />
                  {cfg.label}
                </span>
                <span className="text-sm font-mono font-medium">{a.tool_name}</span>
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide", TIER_COLOR[a.risk_tier] ?? TIER_COLOR.write)}>
                  {a.risk_tier}
                </span>
                {a.agent_name && <span className="text-[10px] text-muted-foreground">from {a.agent_name}</span>}
              </div>

              {Object.keys(a.tool_args || {}).length > 0 && (
                <pre className="text-[10px] bg-muted/40 rounded p-2 overflow-x-auto text-muted-foreground">
                  {JSON.stringify(a.tool_args, null, 2)}
                </pre>
              )}

              {isPending && (
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => approve.mutate(a.id)}
                    disabled={approve.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                  >
                    <CheckCircle className="w-3.5 h-3.5" /> Approve & Run
                  </button>
                  <button
                    onClick={() => deny.mutate(a.id)}
                    disabled={deny.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                  >
                    <XCircle className="w-3.5 h-3.5" /> Deny
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
