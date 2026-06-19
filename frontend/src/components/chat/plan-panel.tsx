"use client";
import { CheckCircle, XCircle, Clock, SkipForward, RotateCcw, X, ClipboardList } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PlanStep {
  id: string;
  plan_id: string;
  position: number;
  title: string;
  description?: string | null;
  status: "pending" | "in_progress" | "done" | "failed" | "skipped";
  note?: string | null;
  task_id?: string | null;
}

export interface Plan {
  id: string;
  chat_id: string;
  title: string;
  status: "active" | "completed" | "cancelled";
  steps: PlanStep[];
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

interface PlanPanelProps {
  plan: Plan | null;
  onClose: () => void;
}

function StepIcon({ status }: { status: PlanStep["status"] }) {
  if (status === "done") return <CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" />;
  if (status === "failed") return <XCircle className="w-3.5 h-3.5 text-destructive shrink-0" />;
  if (status === "skipped") return <SkipForward className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
  if (status === "in_progress") return <RotateCcw className="w-3.5 h-3.5 text-primary shrink-0 animate-spin" />;
  return <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
}

export function PlanPanel({ plan, onClose }: PlanPanelProps) {
  if (!plan) {
    return (
      <div className="flex flex-col h-full w-64 border-l border-border bg-card shrink-0 overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <ClipboardList className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-semibold">Plan</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-muted-foreground text-center px-4">
            No active plan. The Project Manager creates a plan when it starts working on a multi-step objective.
          </p>
        </div>
      </div>
    );
  }

  const total = plan.steps.length;
  const done = plan.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const failed = plan.steps.filter((s) => s.status === "failed").length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="flex flex-col h-full w-64 border-l border-border bg-card shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <ClipboardList className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Plan</span>
          <span
            className={cn(
              "text-[10px] px-1.5 py-0.5 rounded font-mono",
              plan.status === "completed"
                ? "bg-green-500/10 text-green-500"
                : "bg-primary/10 text-primary"
            )}
          >
            {done}/{total}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Plan title + progress */}
      <div className="px-3 py-2.5 border-b border-border shrink-0 space-y-1.5">
        <p className="text-xs font-medium text-foreground leading-tight">{plan.title}</p>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                plan.status === "completed" ? "bg-green-500" : failed > 0 ? "bg-amber-500" : "bg-primary"
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[10px] text-muted-foreground font-mono">{pct}%</span>
        </div>
        {plan.status === "completed" && (
          <p className="text-[10px] text-green-500 font-medium">Plan complete</p>
        )}
      </div>

      {/* Steps */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {plan.steps.map((step) => (
          <div
            key={step.id}
            className={cn(
              "rounded-md border p-2 text-xs transition-colors",
              step.status === "done" || step.status === "skipped"
                ? "border-border bg-muted/20 opacity-70"
                : step.status === "failed"
                ? "border-destructive/30 bg-destructive/5"
                : step.status === "in_progress"
                ? "border-primary/40 bg-primary/5"
                : "border-border bg-card"
            )}
          >
            <div className="flex items-start gap-2">
              <span className="text-[10px] text-muted-foreground font-mono w-4 shrink-0 mt-0.5">
                {step.position + 1}.
              </span>
              <StepIcon status={step.status} />
              <div className="flex-1 min-w-0">
                <p
                  className={cn(
                    "font-medium leading-tight",
                    step.status === "done" || step.status === "skipped"
                      ? "line-through text-muted-foreground"
                      : "text-foreground"
                  )}
                >
                  {step.title}
                </p>
                {step.note && (
                  <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight italic">
                    {step.note}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
