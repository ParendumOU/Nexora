"use client";

import { useMemo } from "react";
import { Bot, Circle, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TaskData } from "./task-panel";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OrgNode {
  id: string;
  label: string;
  sublabel?: string;
  status: string;
  type: "root" | "agent" | "task";
  taskCount?: number;
  doneCount?: number;
  children: OrgNode[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  pending:   "bg-yellow-400",
  running:   "bg-cyan-400 animate-pulse",
  paused:    "bg-orange-400",
  queued:    "bg-blue-400",
  completed: "bg-green-400",
  failed:    "bg-red-400",
};

const STATUS_BORDER: Record<string, string> = {
  running:   "border-cyan-400/40",
  paused:    "border-orange-400/40",
  failed:    "border-red-400/40",
  completed: "border-green-400/30",
  pending:   "border-border",
  queued:    "border-blue-400/40",
};

function dominantStatus(statuses: string[]): string {
  const priority = ["failed", "running", "paused", "queued", "pending", "completed"];
  for (const s of priority) {
    if (statuses.includes(s)) return s;
  }
  return "pending";
}

// ── Node components ───────────────────────────────────────────────────────────

function RootNode({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/30 flex items-center justify-center">
        <Cpu className="w-5 h-5 text-primary" />
      </div>
      <span className="text-[11px] font-semibold text-foreground max-w-[80px] text-center leading-tight">
        {label}
      </span>
    </div>
  );
}

function AgentNode({ node }: { node: OrgNode }) {
  const border = STATUS_BORDER[node.status] ?? "border-border";
  return (
    <div className={cn("bg-card border rounded-lg px-3 py-2 min-w-[120px] max-w-[160px]", border)}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", STATUS_DOT[node.status])} />
        <Bot className="w-3 h-3 text-muted-foreground" />
        <span className="text-xs font-semibold truncate">{node.label}</span>
      </div>
      {node.taskCount !== undefined && (
        <div className="text-[10px] text-muted-foreground">
          {node.doneCount}/{node.taskCount} tasks
        </div>
      )}
    </div>
  );
}

function TaskNode({ node }: { node: OrgNode }) {
  const border = STATUS_BORDER[node.status] ?? "border-border";
  return (
    <div className={cn("bg-accent/30 border rounded-md px-2.5 py-1.5 min-w-[110px] max-w-[150px]", border)}>
      <div className="flex items-center gap-1.5">
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", STATUS_DOT[node.status])} />
        <span className="text-[11px] font-medium truncate leading-tight">{node.label}</span>
      </div>
      {node.sublabel && (
        <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{node.sublabel}</div>
      )}
    </div>
  );
}

// ── Tree rendering ────────────────────────────────────────────────────────────

function Connector({ vertical }: { vertical?: boolean }) {
  return vertical
    ? <div className="w-px bg-border self-stretch" />
    : <div className="h-px bg-border w-6 shrink-0" />;
}

function BranchGroup({ children: nodes }: { children: OrgNode[] }) {
  return (
    <div className="flex flex-col gap-3 relative">
      {/* Vertical spine */}
      {nodes.length > 1 && (
        <div className="absolute left-0 top-0 bottom-0 w-px bg-border" />
      )}
      {nodes.map((node) => (
        <div key={node.id} className="flex items-start gap-0">
          {/* Horizontal notch */}
          {nodes.length > 1 && <div className="w-4 h-px bg-border self-center shrink-0 mt-0" />}
          {node.type === "agent" ? (
            <div className="flex items-start gap-0">
              <AgentNode node={node} />
              {node.children.length > 0 && (
                <>
                  <div className="w-5 h-px bg-border self-center shrink-0" />
                  <BranchGroup>{node.children}</BranchGroup>
                </>
              )}
            </div>
          ) : (
            <TaskNode node={node} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main OrgChart ─────────────────────────────────────────────────────────────

export function OrgChart({
  chatTitle,
  tasks,
  onClose,
}: {
  chatTitle?: string;
  tasks: TaskData[];
  onClose: () => void;
}) {
  const tree = useMemo((): OrgNode => {
    // Build agent nodes from tasks
    const agentMap = new Map<string, { name: string; tasks: TaskData[] }>();

    for (const t of tasks) {
      const key = t.assigned_agent_id ?? "__unassigned__";
      const name = t.assigned_agent_name ?? (t.assigned_agent_id ? "Agent" : "Direct");
      if (!agentMap.has(key)) agentMap.set(key, { name, tasks: [] });
      agentMap.get(key)!.tasks.push(t);
    }

    const agentNodes: OrgNode[] = Array.from(agentMap.entries()).map(([agentId, { name, tasks: agentTasks }]) => {
      const statuses = agentTasks.map((t) => t.status);
      const taskNodes: OrgNode[] = agentTasks
        .filter((t) => !t.parent_id)
        .map((t) => ({
          id: t.id,
          label: t.title,
          sublabel: t.description ?? undefined,
          status: t.status,
          type: "task",
          children: [],
        }));

      return {
        id: agentId,
        label: name,
        status: dominantStatus(statuses),
        type: "agent",
        taskCount: agentTasks.length,
        doneCount: agentTasks.filter((t) => t.status === "completed").length,
        children: taskNodes,
      };
    });

    const rootStatus = agentNodes.length > 0 ? dominantStatus(agentNodes.map((a) => a.status)) : "pending";

    return {
      id: "root",
      label: chatTitle ?? "AI Assistant",
      status: rootStatus,
      type: "root",
      children: agentNodes,
    };
  }, [tasks, chatTitle]);

  return (
    <div className="flex flex-col h-full w-[520px] border-l border-border bg-card shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
        <span className="text-xs font-semibold">Agent Hierarchy</span>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors text-[11px]"
        >
          ✕
        </button>
      </div>

      {/* Empty state */}
      {tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-center px-8">
          <Bot className="w-8 h-8 text-muted-foreground/40" />
          <div>
            <p className="text-sm font-medium">No agents active</p>
            <p className="text-xs text-muted-foreground mt-1">
              The agent hierarchy will appear here as tasks are assigned to sub-agents.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-6">
          {/* Horizontal left-to-right tree */}
          <div className="flex items-start gap-0 min-w-max">
            {/* Root */}
            <RootNode label={tree.label} />

            {tree.children.length > 0 && (
              <>
                <div className="w-8 h-px bg-border self-center shrink-0" />
                <BranchGroup>{tree.children}</BranchGroup>
              </>
            )}
          </div>

          {/* Legend */}
          <div className="mt-8 pt-4 border-t border-border flex items-center gap-4 flex-wrap">
            {[
              { status: "running", label: "Running" },
              { status: "paused", label: "Paused" },
              { status: "pending", label: "Pending" },
              { status: "completed", label: "Done" },
              { status: "failed", label: "Failed" },
            ].map(({ status, label }) => (
              <span key={status} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <span className={cn("w-1.5 h-1.5 rounded-full", STATUS_DOT[status])} />
                {label}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
