"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { approvalsApi } from "@/lib/api";
import { ShieldCheck, CheckCircle, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, FilterBar, PageLoading, PageEmpty,
} from "@/components/layout/page-shell";

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
    <PageShell>
      <PageHeader
        icon={ShieldCheck}
        title="Approvals"
        subtitle="Review tool actions held for human approval"
      />

      <FilterBar
        options={FILTERS.map((f) => ({
          id: f,
          label: f === "all" ? "All" : STATUS[f]?.label ?? f,
        }))}
        value={filter}
        onChange={setFilter}
      />

      <PageBody className="px-6 py-4 space-y-3">
        {isLoading && <PageLoading />}

        {!isLoading && (!approvals || approvals.length === 0) && (
          <PageEmpty
            icon={ShieldCheck}
            message={`No approvals ${filter !== "all" ? `with status "${filter}"` : "yet"}`}
          />
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
      </PageBody>
    </PageShell>
  );
}
