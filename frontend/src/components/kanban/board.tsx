"use client";
import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, LayoutDashboard } from "lucide-react";
import { boardApi, tasksApi } from "@/lib/api";
import { KanbanColumn } from "./column";
import { InterruptDialog } from "./interrupt-dialog";
import { COLUMN_ORDER, type BoardColumns, type ColumnId, type KanbanTask } from "./types";

type Props = {
  projectId: string;
  agentId?: string;
};

export function KanbanBoard({ projectId, agentId }: Props) {
  const qc = useQueryClient();
  const draggingTask = useRef<KanbanTask | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [interruptingTask, setInterruptingTask] = useState<KanbanTask | null>(null);

  const { data: columns, isLoading } = useQuery<BoardColumns>({
    queryKey: ["board", projectId, agentId],
    queryFn: () => boardApi.byProject(projectId, agentId).then((r) => r.data),
    refetchInterval: 20000,
  });

  const allTasks: KanbanTask[] = columns
    ? COLUMN_ORDER.flatMap((col) => columns[col] ?? [])
    : [];

  const handleDragStart = useCallback((task: KanbanTask) => {
    draggingTask.current = task;
    setDraggingId(task.id);
  }, []);

  const handleDrop = useCallback(
    async (targetColumn: ColumnId) => {
      const task = draggingTask.current;
      draggingTask.current = null;
      setDraggingId(null);
      if (!task || task.status === targetColumn) return;

      // Optimistic update
      qc.setQueryData<BoardColumns>(["board", projectId, agentId], (prev) => {
        if (!prev) return prev;
        const next: BoardColumns = { ...prev };
        COLUMN_ORDER.forEach((col) => {
          next[col] = (prev[col] ?? []).filter((t) => t.id !== task.id);
        });
        next[targetColumn] = [
          ...(next[targetColumn] ?? []),
          { ...task, status: targetColumn },
        ];
        return next;
      });

      try {
        await tasksApi.update(task.id, { status: targetColumn });
        qc.invalidateQueries({ queryKey: ["board", projectId, agentId] });
      } catch {
        qc.invalidateQueries({ queryKey: ["board", projectId, agentId] });
      }
    },
    [projectId, qc]
  );

  const handleInterrupt = useCallback((task: KanbanTask) => {
    setInterruptingTask(task);
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading board…
      </div>
    );
  }

  if (!columns) return null;

  const isEmpty = allTasks.length === 0;

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
        <LayoutDashboard className="w-10 h-10 opacity-20" />
        <p className="text-sm">No tasks yet — the agent will populate this board.</p>
      </div>
    );
  }

  return (
    <>
      <div
        className="flex gap-3 overflow-x-auto pb-4 h-full"
        onDragEnd={() => {
          draggingTask.current = null;
          setDraggingId(null);
        }}
      >
        {COLUMN_ORDER.map((col) => (
          <KanbanColumn
            key={col}
            columnId={col}
            tasks={columns[col] ?? []}
            allTasks={allTasks}
            draggingTask={draggingId ? (allTasks.find((t) => t.id === draggingId) ?? null) : null}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
            onInterrupt={handleInterrupt}
          />
        ))}
      </div>

      <InterruptDialog
        task={interruptingTask}
        projectId={projectId}
        onClose={() => setInterruptingTask(null)}
      />
    </>
  );
}
