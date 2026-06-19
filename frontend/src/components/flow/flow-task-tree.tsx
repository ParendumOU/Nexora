"use client";

import { useState } from "react";
import {
  ChevronRight, ChevronDown, Bot, CheckCircle2, AlertCircle,
  ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TaskData } from "@/components/chat/task-panel";

// ── Status config ─────────────────────────────────────────────────────────────

export const FLOW_STATUS: Record<string, { dot: string; bar: string; label: string; text: string }> = {
  pending:     { dot: "bg-yellow-400",             bar: "bg-yellow-400/30",  label: "Pending",   text: "text-yellow-400"  },
  queued:      { dot: "bg-blue-400",               bar: "bg-blue-400/30",    label: "Queued",    text: "text-blue-400"    },
  in_progress: { dot: "bg-cyan-400 animate-pulse", bar: "bg-cyan-400/30",    label: "Running",   text: "text-cyan-400"    },
  running:     { dot: "bg-cyan-400 animate-pulse", bar: "bg-cyan-400/30",    label: "Running",   text: "text-cyan-400"    },
  paused:      { dot: "bg-orange-400",             bar: "bg-orange-400/30",  label: "Paused",    text: "text-orange-400"  },
  completed:   { dot: "bg-green-400",              bar: "bg-green-400/30",   label: "Done",      text: "text-green-400"   },
  failed:      { dot: "bg-red-400",                bar: "bg-red-400/30",     label: "Failed",    text: "text-red-400"     },
};

const PAGE_SIZE = 10;

// Active statuses are shown open by default; done/failed are collapsed.
const ACTIVE_STATUSES = new Set(["pending", "queued", "in_progress", "running", "paused"]);

// ── Single task row (recursive) ───────────────────────────────────────────────

function TaskRow({
  task,
  allTasks,
  depth,
  selectedId,
  onSelect,
}: {
  task: TaskData;
  allTasks: TaskData[];
  depth: number;
  selectedId: string | null;
  onSelect: (task: TaskData) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const children = allTasks.filter((t) => t.parent_id === task.id);
  const cfg = FLOW_STATUS[task.status] ?? FLOW_STATUS.pending;
  const isSelected = selectedId === task.id;
  const doneItems = task.checklist.filter((c) => c.done).length;

  return (
    <div className={cn("select-none", depth > 0 && "ml-3.5 border-l border-border/40 pl-2.5")}>
      <div
        onClick={() => onSelect(task)}
        className={cn(
          "group flex items-start gap-1.5 py-1.5 px-2 rounded-lg cursor-pointer transition-all",
          isSelected ? "bg-primary/10 ring-1 ring-primary/25" : "hover:bg-accent/50"
        )}
      >
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
          className="mt-0.5 shrink-0 w-3 text-muted-foreground hover:text-foreground transition-colors"
        >
          {children.length > 0 ? (
            expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />
          ) : (
            <span className="w-3 h-3 block" />
          )}
        </button>
        <span className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0 block", cfg.dot)} />
        <div className="flex-1 min-w-0">
          <span className={cn(
            "text-xs font-medium leading-snug block truncate",
            isSelected ? "text-primary" : "text-foreground"
          )}>
            {task.title}
          </span>
          {task.assigned_agent_name && (
            <span className="flex items-center gap-1 mt-0.5">
              <Bot className="w-2.5 h-2.5 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground truncate">{task.assigned_agent_name}</span>
            </span>
          )}
        </div>
        {task.checklist.length > 0 && (
          <span className={cn(
            "text-[9px] font-mono shrink-0 px-1 py-0.5 rounded self-center",
            doneItems === task.checklist.length
              ? "text-green-400 bg-green-400/10"
              : "text-muted-foreground bg-accent/60"
          )}>
            {doneItems}/{task.checklist.length}
          </span>
        )}
        {task.status === "failed" && (
          <AlertCircle className="w-3 h-3 text-red-400 shrink-0 self-center" />
        )}
      </div>
      {expanded && children.map((child) => (
        <TaskRow
          key={child.id}
          task={child}
          allTasks={allTasks}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

// ── Paginated status section ──────────────────────────────────────────────────

function TaskSection({
  status,
  tasks,
  allTasks,
  selectedId,
  onSelect,
  defaultOpen,
}: {
  status: string;
  tasks: TaskData[];
  allTasks: TaskData[];
  selectedId: string | null;
  onSelect: (task: TaskData) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [page, setPage] = useState(0);

  if (tasks.length === 0) return null;

  const cfg = FLOW_STATUS[status] ?? FLOW_STATUS.pending;
  const totalPages = Math.ceil(tasks.length / PAGE_SIZE);
  const pageTasks = tasks.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="border-b border-border/40 last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-accent/40 transition-colors text-left"
      >
        {open
          ? <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
          : <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
        }
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", cfg.dot)} />
        <span className="text-[11px] font-semibold text-muted-foreground flex-1">{cfg.label}</span>
        <span className="text-[10px] font-mono text-muted-foreground bg-accent/60 px-1.5 py-0.5 rounded">
          {tasks.length}
        </span>
      </button>

      {open && (
        <>
          <div className="px-2 pb-1 space-y-0.5">
            {pageTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                allTasks={allTasks}
                depth={0}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-3 py-1.5 border-t border-border/40">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="p-1 rounded hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-3 h-3 text-muted-foreground" />
              </button>
              <span className="text-[10px] text-muted-foreground font-mono">
                {page + 1} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
                className="p-1 rounded hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight className="w-3 h-3 text-muted-foreground" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── FlowTaskTree export ───────────────────────────────────────────────────────

// Render order: active statuses first (open), then done and failed (collapsed).
const SECTION_ORDER: string[] = ["in_progress", "running", "queued", "pending", "paused", "completed", "failed"];

export function FlowTaskTree({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: TaskData[];
  selectedId: string | null;
  onSelect: (task: TaskData) => void;
}) {
  const rootTasks = tasks.filter((t) => !t.parent_id);

  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});
  const totalDone = counts["completed"] ?? 0;

  // Group root tasks by status
  const byStatus: Record<string, TaskData[]> = {};
  for (const task of rootTasks) {
    (byStatus[task.status] ??= []).push(task);
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Status summary bar */}
      {tasks.length > 0 && (
        <div className="px-3 py-2 border-b border-border shrink-0 space-y-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-border rounded-full overflow-hidden">
              <div
                className="h-full bg-green-400 rounded-full transition-all duration-500"
                style={{ width: `${tasks.length ? (totalDone / tasks.length) * 100 : 0}%` }}
              />
            </div>
            <span className="text-[10px] font-mono text-muted-foreground shrink-0">
              {totalDone}/{tasks.length}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {Object.entries(FLOW_STATUS)
              .filter(([s]) => counts[s])
              .map(([s, c]) => (
                <span key={s} className="flex items-center gap-1 text-[10px]">
                  <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", c.dot)} />
                  <span className="text-muted-foreground">{counts[s]} {c.label}</span>
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Grouped sections */}
      <div className="flex-1 overflow-y-auto">
        {rootTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2 text-center px-4">
            <div className="w-9 h-9 rounded-full bg-accent/50 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4 text-muted-foreground" />
            </div>
            <p className="text-xs text-muted-foreground">No tasks yet</p>
            <p className="text-[11px] text-muted-foreground/60">Tasks created by agents appear here</p>
          </div>
        ) : (
          SECTION_ORDER.map((status) => (
            <TaskSection
              key={status}
              status={status}
              tasks={byStatus[status] ?? []}
              allTasks={tasks}
              selectedId={selectedId}
              onSelect={onSelect}
              defaultOpen={ACTIVE_STATUSES.has(status)}
            />
          ))
        )}
      </div>
    </div>
  );
}
