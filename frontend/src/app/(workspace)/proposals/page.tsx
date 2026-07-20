"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { proposalsApi } from "@/lib/api";
import { Lightbulb, CheckCircle, XCircle, Clock, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PageShell, PageHeader, PageBody, FilterBar, PageLoading, PageEmpty,
} from "@/components/layout/page-shell";

type Proposal = {
  id: string;
  proposal_type: string;
  title: string;
  rationale: string | null;
  payload: Record<string, unknown>;
  confidence: number;
  status: string;
  agent_name: string | null;
  execution_result: Record<string, unknown> | null;
  reviewed_at: string | null;
  created_at: string;
};

const STATUS_CONFIG: Record<string, { label: string; className: string; icon: React.FC<{ className?: string }> }> = {
  pending:       { label: "Pending",       className: "bg-yellow-400/15 text-yellow-400",  icon: Clock },
  approved:      { label: "Approved",      className: "bg-green-400/15 text-green-400",    icon: CheckCircle },
  rejected:      { label: "Rejected",      className: "bg-red-400/15 text-red-400",        icon: XCircle },
  auto_approved: { label: "Auto-approved", className: "bg-blue-400/15 text-blue-400",      icon: Zap },
};

const FILTERS = ["all", "pending", "approved", "rejected", "auto_approved"] as const;

function confidenceBar(c: number) {
  const pct = Math.round(c * 100);
  const color = c >= 0.85 ? "bg-green-400" : c >= 0.6 ? "bg-yellow-400" : "bg-orange-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground tabular-nums w-8 text-right">{pct}%</span>
    </div>
  );
}

export default function ProposalsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<typeof FILTERS[number]>("pending");

  const { data: proposals, isLoading } = useQuery<Proposal[]>({
    queryKey: ["proposals", filter],
    queryFn: () => proposalsApi.list(filter === "all" ? undefined : filter).then((r) => r.data),
    refetchInterval: 15000,
  });

  const approve = useMutation({
    mutationFn: (id: string) => proposalsApi.approve(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proposals"] }),
  });

  const reject = useMutation({
    mutationFn: (id: string) => proposalsApi.reject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proposals"] }),
  });

  return (
    <PageShell>
      <PageHeader
        icon={Lightbulb}
        title="Agent Proposals"
        subtitle="Review proactive suggestions from agents"
      />

      <FilterBar
        options={FILTERS.map((f) => ({
          id: f,
          label: f === "all" ? "All" : STATUS_CONFIG[f]?.label ?? f,
        }))}
        value={filter}
        onChange={setFilter}
      />

      <PageBody className="px-6 py-4 space-y-3">
        {isLoading && <PageLoading />}

        {!isLoading && (!proposals || proposals.length === 0) && (
          <PageEmpty
            icon={Lightbulb}
            message={`No proposals ${filter !== "all" ? `with status "${filter}"` : "yet"}`}
          />
        )}

        {proposals?.map((p) => {
          const cfg = STATUS_CONFIG[p.status] ?? STATUS_CONFIG.pending;
          const Icon = cfg.icon;
          const isPending = p.status === "pending";
          return (
            <div key={p.id} className="border border-border rounded-lg p-4 bg-card space-y-3">
              {/* Header */}
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide", cfg.className)}>
                      <Icon className="w-3 h-3 inline mr-1" />
                      {cfg.label}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase tracking-wide">
                      {p.proposal_type}
                    </span>
                    {p.agent_name && (
                      <span className="text-[10px] text-muted-foreground">from {p.agent_name}</span>
                    )}
                  </div>
                  <p className="text-sm font-medium leading-snug">{p.title}</p>
                </div>
              </div>

              {/* Rationale */}
              {p.rationale && (
                <p className="text-xs text-muted-foreground leading-relaxed">{p.rationale}</p>
              )}

              {/* Confidence */}
              <div>
                <p className="text-[10px] text-muted-foreground mb-1">Confidence</p>
                {confidenceBar(p.confidence)}
              </div>

              {/* Payload preview */}
              {Object.keys(p.payload).length > 0 && (
                <details className="group">
                  <summary className="text-[10px] text-muted-foreground cursor-pointer select-none hover:text-foreground">
                    Payload ({Object.keys(p.payload).length} fields)
                  </summary>
                  <pre className="mt-2 text-[10px] bg-muted/40 rounded p-2 overflow-x-auto text-muted-foreground">
                    {JSON.stringify(p.payload, null, 2)}
                  </pre>
                </details>
              )}

              {/* Execution result */}
              {p.execution_result && (
                <details>
                  <summary className="text-[10px] text-muted-foreground cursor-pointer select-none hover:text-foreground">
                    Execution result
                  </summary>
                  <pre className="mt-2 text-[10px] bg-muted/40 rounded p-2 overflow-x-auto text-muted-foreground">
                    {JSON.stringify(p.execution_result, null, 2)}
                  </pre>
                </details>
              )}

              {/* Actions */}
              {isPending && (
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => approve.mutate(p.id)}
                    disabled={approve.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                  >
                    <CheckCircle className="w-3.5 h-3.5" />
                    Approve & Execute
                  </button>
                  <button
                    onClick={() => reject.mutate(p.id)}
                    disabled={reject.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    Reject
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
