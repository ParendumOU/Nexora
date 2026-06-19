"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus, ChevronRight, ChevronDown, Trash2,
  Circle, CheckCircle2, XCircle, PauseCircle, Clock, ListTodo, Bot,
  MoreHorizontal, Play, Square,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { tasksApi, agentsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TaskData {
  id: string;
  chat_id: string;
  parent_id: string | null;
  position: number;
  title: string;
  description: string | null;
  output: string | null;
  status: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  model_override: string | null;
  checklist: Array<{ id: string; item: string; done: boolean }>;
  sub_chat_id: string | null;
  created_after_message_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  steps?: Array<{ step_id: string; name: string; label: string; status: string; error?: string | null }>;
}

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { dot: string; label: string }> = {
  pending:   { dot: "bg-yellow-400",             label: "Pending" },
  running:   { dot: "bg-cyan-400 animate-pulse", label: "Running" },
  paused:    { dot: "bg-orange-400",             label: "Paused" },
  queued:    { dot: "bg-blue-400",               label: "Queued" },
  completed: { dot: "bg-green-400",              label: "Done" },
  failed:    { dot: "bg-red-400",                label: "Failed" },
};

const STATUS_CYCLE: Record<string, string> = {
  pending: "running",
  running: "paused",
  paused:  "running",
  queued:  "running",
  completed: "pending",
  failed:  "pending",
};

// ── Checklist item ────────────────────────────────────────────────────────────

function ChecklistRow({
  item, onToggle,
}: {
  item: { id: string; item: string; done: boolean };
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-start gap-1.5 w-full text-left group/check py-0.5"
    >
      <span className={cn(
        "mt-0.5 shrink-0 w-3.5 h-3.5 rounded border flex items-center justify-center transition-colors",
        item.done
          ? "bg-green-500 border-green-500 text-white"
          : "border-border bg-transparent group-hover/check:border-muted-foreground"
      )}>
        {item.done && <CheckCircle2 className="w-2.5 h-2.5" />}
      </span>
      <span className={cn(
        "text-[11px] leading-relaxed",
        item.done ? "line-through text-muted-foreground" : "text-foreground"
      )}>
        {item.item}
      </span>
    </button>
  );
}

// ── Task row (recursive) ──────────────────────────────────────────────────────

function TaskRow({
  task,
  allTasks,
  depth,
  agents,
  onUpdate,
  onDelete,
  onAddChild,
}: {
  task: TaskData;
  allTasks: TaskData[];
  depth: number;
  agents: Array<{ id: string; name: string }>;
  onUpdate: (id: string, data: Record<string, unknown>) => void;
  onDelete: (id: string) => void;
  onAddChild: (parentId: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const children = allTasks.filter((t) => t.parent_id === task.id);
  const cfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.pending;
  const doneCount = task.checklist.filter((c) => c.done).length;

  const toggleChecklist = (itemId: string) => {
    const updated = task.checklist.map((c) =>
      c.id === itemId ? { ...c, done: !c.done } : c
    );
    onUpdate(task.id, { checklist: updated });
  };

  const cycleStatus = () => {
    onUpdate(task.id, { status: STATUS_CYCLE[task.status] ?? "pending" });
  };

  return (
    <div className={cn("select-none", depth > 0 && "ml-4 border-l border-border pl-2")}>
      {/* Task header */}
      <div className="group/task flex items-start gap-1.5 py-1.5 rounded hover:bg-accent/40 px-1 -mx-1">
        {/* Expand toggle */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground transition-colors"
        >
          {children.length > 0 ? (
            expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />
          ) : (
            <span className="w-3 h-3 block" />
          )}
        </button>

        {/* Status dot */}
        <button onClick={cycleStatus} title={`Status: ${cfg.label} — click to advance`}>
          <span className={cn("w-2 h-2 rounded-full mt-1 shrink-0 block", cfg.dot)} />
        </button>

        {/* Title */}
        <span className="flex-1 text-xs font-medium leading-relaxed min-w-0 truncate">
          {task.title}
        </span>

        {/* Checklist progress badge */}
        {task.checklist.length > 0 && (
          <span className={cn(
            "text-[10px] font-mono shrink-0 px-1 rounded",
            doneCount === task.checklist.length
              ? "text-green-400 bg-green-400/10"
              : "text-muted-foreground bg-accent/50"
          )}>
            {doneCount}/{task.checklist.length}
          </span>
        )}

        {/* Actions menu */}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className="opacity-0 group-hover/task:opacity-100 shrink-0 p-0.5 rounded hover:bg-accent transition-all">
              <MoreHorizontal className="w-3 h-3 text-muted-foreground" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              className="z-50 min-w-[140px] bg-popover border border-border rounded-lg shadow-md p-1 text-xs"
              sideOffset={4}
            >
              {/* Status submenu */}
              {Object.entries(STATUS_CONFIG).map(([s, c]) => (
                <DropdownMenu.Item
                  key={s}
                  onSelect={() => onUpdate(task.id, { status: s })}
                  className={cn(
                    "flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer outline-none",
                    "hover:bg-accent text-foreground",
                    task.status === s && "text-muted-foreground"
                  )}
                >
                  <span className={cn("w-2 h-2 rounded-full shrink-0", c.dot)} />
                  {c.label}
                </DropdownMenu.Item>
              ))}

              <DropdownMenu.Separator className="my-1 border-t border-border" />

              {/* Agent assign */}
              {agents.map((a) => (
                <DropdownMenu.Item
                  key={a.id}
                  onSelect={() => onUpdate(task.id, { assigned_agent_id: a.id })}
                  className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer outline-none hover:bg-accent text-foreground"
                >
                  <Bot className="w-3 h-3 text-muted-foreground" />
                  {a.name}
                </DropdownMenu.Item>
              ))}

              <DropdownMenu.Separator className="my-1 border-t border-border" />

              <DropdownMenu.Item
                onSelect={() => onAddChild(task.id)}
                className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer outline-none hover:bg-accent text-foreground"
              >
                <Plus className="w-3 h-3" /> Add subtask
              </DropdownMenu.Item>

              <DropdownMenu.Item
                onSelect={() => onDelete(task.id)}
                className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer outline-none hover:bg-destructive/10 text-destructive"
              >
                <Trash2 className="w-3 h-3" /> Delete
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      {/* Agent badge */}
      {expanded && task.assigned_agent_name && (
        <div className="flex items-center gap-1 ml-6 mb-1">
          <Bot className="w-2.5 h-2.5 text-muted-foreground" />
          <span className="text-[10px] text-muted-foreground">{task.assigned_agent_name}</span>
          {task.model_override && (
            <span className="text-[10px] font-mono text-muted-foreground">· {task.model_override}</span>
          )}
        </div>
      )}

      {/* Checklist */}
      {expanded && task.checklist.length > 0 && (
        <div className="ml-6 mb-1 space-y-0.5">
          {task.checklist.map((c) => (
            <ChecklistRow key={c.id} item={c} onToggle={() => toggleChecklist(c.id)} />
          ))}
        </div>
      )}

      {/* Output snippet */}
      {expanded && task.output && task.status === "completed" && (
        <div className="ml-6 mb-1 text-[10px] text-muted-foreground italic truncate max-w-[200px]">
          {task.output.slice(0, 80)}{task.output.length > 80 ? "…" : ""}
        </div>
      )}

      {/* Children */}
      {expanded && children.map((child) => (
        <TaskRow
          key={child.id}
          task={child}
          allTasks={allTasks}
          depth={depth + 1}
          agents={agents}
          onUpdate={onUpdate}
          onDelete={onDelete}
          onAddChild={onAddChild}
        />
      ))}
    </div>
  );
}

// ── New task inline form ──────────────────────────────────────────────────────

function NewTaskForm({
  chatId,
  parentId,
  onDone,
  onCancel,
}: {
  chatId: string;
  parentId: string | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      tasksApi.create({ chat_id: chatId, title: title.trim(), parent_id: parentId ?? undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", chatId] });
      onDone();
    },
    onError: () => toast.error("Failed to create task"),
  });

  const submit = () => {
    if (!title.trim()) return;
    create.mutate();
  };

  return (
    <div className="flex items-center gap-1.5 py-1">
      <span className="w-2 h-2 rounded-full bg-yellow-400 shrink-0" />
      <Input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") onCancel();
        }}
        placeholder="Task title…"
        className="h-6 text-xs py-0 px-2 flex-1 bg-accent/30"
      />
      <button
        onClick={submit}
        disabled={!title.trim() || create.isPending}
        className="text-[10px] text-primary hover:text-primary/80 font-medium disabled:opacity-40"
      >
        Add
      </button>
      <button onClick={onCancel} className="text-[10px] text-muted-foreground hover:text-foreground">
        ✕
      </button>
    </div>
  );
}

// ── Main TaskPanel ────────────────────────────────────────────────────────────

export function TaskPanel({
  chatId,
  tasks,
  onClose,
}: {
  chatId: string;
  tasks: TaskData[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [addingParent, setAddingParent] = useState<string | "root" | false>(false);

  const { data: agents = [] } = useQuery({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });

  const updateTask = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      tasksApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", chatId] }),
    onError: () => toast.error("Failed to update task"),
  });

  const deleteTask = useMutation({
    mutationFn: (id: string) => tasksApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", chatId] }),
    onError: () => toast.error("Failed to delete task"),
  });

  const handleUpdate = useCallback(
    (id: string, data: Record<string, unknown>) => updateTask.mutate({ id, data }),
    [updateTask]
  );

  const handleDelete = useCallback(
    (id: string) => deleteTask.mutate(id),
    [deleteTask]
  );

  const rootTasks = tasks.filter((t) => !t.parent_id);
  const totalDone = tasks.filter((t) => t.status === "completed").length;

  // Summary counts
  const counts = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col h-full w-72 border-l border-border bg-card shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <ListTodo className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Tasks</span>
          {tasks.length > 0 && (
            <span className="text-[10px] bg-accent px-1.5 py-0.5 rounded font-mono text-muted-foreground">
              {totalDone}/{tasks.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setAddingParent("root")}
            className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            title="New root task"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <XCircle className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Status summary pills */}
      {tasks.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border flex-wrap shrink-0">
          {Object.entries(STATUS_CONFIG)
            .filter(([s]) => counts[s])
            .map(([s, c]) => (
              <span key={s} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <span className={cn("w-1.5 h-1.5 rounded-full", c.dot)} />
                {counts[s]}
              </span>
            ))}
        </div>
      )}

      {/* Task tree */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {/* New root task form */}
        {addingParent === "root" && (
          <NewTaskForm
            chatId={chatId}
            parentId={null}
            onDone={() => setAddingParent(false)}
            onCancel={() => setAddingParent(false)}
          />
        )}

        {rootTasks.length === 0 && addingParent !== "root" && (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center">
            <ListTodo className="w-6 h-6 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">No tasks yet</p>
            <button
              onClick={() => setAddingParent("root")}
              className="text-[11px] text-primary hover:underline"
            >
              Create first task
            </button>
          </div>
        )}

        {rootTasks.map((task) => (
          <div key={task.id}>
            {/* Inline "add child" form */}
            {addingParent === task.id && (
              <div className="ml-6">
                <NewTaskForm
                  chatId={chatId}
                  parentId={task.id}
                  onDone={() => setAddingParent(false)}
                  onCancel={() => setAddingParent(false)}
                />
              </div>
            )}
            <TaskRow
              task={task}
              allTasks={tasks}
              depth={0}
              agents={agents}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
              onAddChild={(pid) => setAddingParent(pid)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
