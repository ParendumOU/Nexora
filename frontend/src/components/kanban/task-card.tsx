"use client";
import { AlertTriangle, Bot, CheckSquare, StopCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { KanbanTask } from "./types";
import { PRIORITY_CONFIG } from "./types";

const INTERRUPTIBLE = new Set(["queued", "in_progress", "running"]);

type Props = {
  task: KanbanTask;
  allTasks: KanbanTask[];
  isDragging: boolean;
  onDragStart: (task: KanbanTask) => void;
  onInterrupt: (task: KanbanTask) => void;
};

export function TaskCard({ task, allTasks, isDragging, onDragStart, onInterrupt }: Props) {
  const priorityCfg = PRIORITY_CONFIG[task.priority] ?? PRIORITY_CONFIG.medium;
  const done = task.checklist.filter((c) => c.done).length;
  const total = task.checklist.length;
  const blockerTitles = task.blocked_by
    .map((id) => allTasks.find((t) => t.id === id)?.title ?? id.slice(0, 8))
    .slice(0, 2);
  const canInterrupt = !!task.assigned_agent_id && INTERRUPTIBLE.has(task.status);

  return (
    <div
      draggable
      onDragStart={() => onDragStart(task)}
      className={cn(
        "group p-3 rounded-lg border bg-card cursor-grab active:cursor-grabbing select-none transition-all",
        "hover:border-border hover:shadow-sm",
        isDragging ? "opacity-40 scale-95" : "border-border/50"
      )}
    >
      {/* Priority + title */}
      <div className="flex items-start gap-2 mb-1.5">
        <span
          className={cn(
            "shrink-0 mt-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide",
            priorityCfg.className
          )}
        >
          {task.priority === "medium" ? null : priorityCfg.label}
        </span>
        <p className="text-xs font-medium leading-snug flex-1 line-clamp-2">{task.title}</p>
      </div>

      {/* Description */}
      {task.description && (
        <p className="text-[11px] text-muted-foreground line-clamp-2 mb-2 leading-relaxed">
          {task.description}
        </p>
      )}

      {/* Checklist progress */}
      {total > 0 && (
        <div className="flex items-center gap-1.5 mb-2">
          <CheckSquare className="w-3 h-3 text-muted-foreground shrink-0" />
          <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-green-400 rounded-full transition-all"
              style={{ width: `${(done / total) * 100}%` }}
            />
          </div>
          <span className="text-[10px] text-muted-foreground tabular-nums">
            {done}/{total}
          </span>
        </div>
      )}

      {/* Footer: blockers + agent + interrupt */}
      <div className="flex items-center gap-2 flex-wrap">
        {blockerTitles.length > 0 && (
          <div className="flex items-center gap-1 text-[10px] text-orange-400">
            <AlertTriangle className="w-3 h-3 shrink-0" />
            <span className="truncate max-w-[120px]">
              Blocked by: {blockerTitles.join(", ")}
              {task.blocked_by.length > 2 ? ` +${task.blocked_by.length - 2}` : ""}
            </span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {task.assigned_agent_id && (
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <Bot className="w-3 h-3" />
              {task.assigned_agent_name && (
                <span className="hidden group-hover:inline truncate max-w-[80px]">
                  {task.assigned_agent_name}
                </span>
              )}
            </div>
          )}
          {canInterrupt && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onInterrupt(task);
              }}
              title="Interrupt or reassign"
              className={cn(
                "opacity-0 group-hover:opacity-100 transition-opacity",
                "flex items-center justify-center w-5 h-5 rounded",
                "text-orange-400 hover:text-orange-300 hover:bg-orange-400/10"
              )}
            >
              <StopCircle className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
