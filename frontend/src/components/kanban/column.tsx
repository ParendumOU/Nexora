"use client";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { TaskCard } from "./task-card";
import type { ColumnId, KanbanTask } from "./types";
import { COLUMN_CONFIG } from "./types";

type Props = {
  columnId: ColumnId;
  tasks: KanbanTask[];
  allTasks: KanbanTask[];
  draggingTask: KanbanTask | null;
  onDragStart: (task: KanbanTask) => void;
  onDrop: (targetColumn: ColumnId) => void;
  onInterrupt: (task: KanbanTask) => void;
};

export function KanbanColumn({ columnId, tasks, allTasks, draggingTask, onDragStart, onDrop, onInterrupt }: Props) {
  const [isOver, setIsOver] = useState(false);
  const cfg = COLUMN_CONFIG[columnId];
  const isDraggingFromHere = draggingTask?.status === columnId;

  return (
    <div
      className={cn(
        "flex flex-col min-w-[240px] w-64 shrink-0 rounded-xl border bg-card/50 transition-colors",
        isOver && !isDraggingFromHere ? "border-primary/50 bg-primary/5" : "border-border/50"
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setIsOver(true);
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={() => {
        setIsOver(false);
        onDrop(columnId);
      }}
    >
      {/* Column header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/50">
        <span className={cn("w-2 h-2 rounded-full shrink-0", cfg.dot)} />
        <span className="text-xs font-semibold text-foreground">{cfg.label}</span>
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{tasks.length}</span>
      </div>

      {/* Cards */}
      <div className="flex-1 p-2 space-y-2 overflow-y-auto min-h-[80px]">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            allTasks={allTasks}
            isDragging={draggingTask?.id === task.id}
            onDragStart={onDragStart}
            onInterrupt={onInterrupt}
          />
        ))}
        {isOver && !isDraggingFromHere && (
          <div className="h-12 rounded-lg border-2 border-dashed border-primary/30 bg-primary/5 flex items-center justify-center">
            <span className="text-[11px] text-primary/60">Drop here</span>
          </div>
        )}
      </div>
    </div>
  );
}
