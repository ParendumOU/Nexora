"use client";

import { useRouter } from "next/navigation";
import {
  X, Bot, Clock, CheckCircle2, MessageSquare, ExternalLink,
  FileText, ChevronRight, Loader2, SlidersHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import { TaskData } from "@/components/chat/task-panel";
import { FLOW_STATUS } from "@/components/flow/flow-task-tree";

export function TaskDetailPanel({
  task,
  allTasks,
  onClose,
  onSelectTask,
}: {
  task: TaskData;
  allTasks: TaskData[];
  onClose: () => void;
  onSelectTask: (task: TaskData) => void;
}) {
  const router = useRouter();
  const cfg = FLOW_STATUS[task.status] ?? FLOW_STATUS.pending;
  const doneItems = task.checklist.filter((c) => c.done).length;
  const children = allTasks.filter((t) => t.parent_id === task.id);
  const parent = task.parent_id ? allTasks.find((t) => t.id === task.parent_id) : null;

  return (
    <div className="flex flex-col h-full w-80 border-l border-border bg-card shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-4 py-3 border-b border-border shrink-0 gap-2">
        <div className="flex items-start gap-2 min-w-0 flex-1">
          <span className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0", cfg.dot)} />
          <div className="min-w-0">
            <h3 className="text-xs font-semibold leading-snug break-words">{task.title}</h3>
            <span className={cn("text-[10px] font-medium", cfg.text)}>{cfg.label}</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Open conversation — primary CTA when sub-chat exists */}
      {task.sub_chat_id && (
        <div className="px-4 pt-3 pb-0 shrink-0">
          <button
            onClick={() => router.push(`/chat/${task.sub_chat_id}`)}
            className="flex items-center justify-between w-full px-3 py-2.5 rounded-lg bg-primary/10 border border-primary/30 hover:bg-primary/20 transition-colors group"
          >
            <div className="flex items-center gap-2">
              <MessageSquare className="w-3.5 h-3.5 text-primary shrink-0" />
              <span className="text-xs font-semibold text-primary">Open conversation</span>
            </div>
            <ExternalLink className="w-3 h-3 text-primary/70 group-hover:text-primary transition-colors shrink-0" />
          </button>
        </div>
      )}

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">

        {/* Breadcrumb */}
        {parent && (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <button
              onClick={() => onSelectTask(parent)}
              className="hover:text-foreground transition-colors truncate max-w-[120px]"
            >
              {parent.title}
            </button>
            <ChevronRight className="w-3 h-3 shrink-0" />
            <span className="text-foreground truncate">{task.title}</span>
          </div>
        )}

        {/* Meta */}
        <div className="space-y-1.5">
          {task.assigned_agent_name && (
            <div className="flex items-center gap-2">
              <Bot className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <span className="text-xs text-foreground">{task.assigned_agent_name}</span>
              {task.model_override && (
                <span className="text-[10px] font-mono text-muted-foreground">· {task.model_override}</span>
              )}
            </div>
          )}
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <span className="text-[11px] text-muted-foreground">Created {formatDate(task.created_at)}</span>
          </div>
          {task.completed_at && (
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />
              <span className="text-[11px] text-muted-foreground">Completed {formatDate(task.completed_at)}</span>
            </div>
          )}
        </div>

        {/* Description */}
        {task.description && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Description</p>
            <p className="text-xs text-foreground leading-relaxed">{task.description}</p>
          </div>
        )}

        {/* Checklist */}
        {task.checklist.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Checklist</p>
              <span className="text-[10px] text-muted-foreground font-mono">{doneItems}/{task.checklist.length}</span>
            </div>
            {/* Mini progress bar */}
            <div className="h-0.5 bg-border rounded-full overflow-hidden mb-2">
              <div
                className="h-full bg-green-400 rounded-full transition-all"
                style={{ width: `${task.checklist.length ? (doneItems / task.checklist.length) * 100 : 0}%` }}
              />
            </div>
            <div className="space-y-1.5">
              {task.checklist.map((item) => (
                <div key={item.id} className="flex items-start gap-2">
                  <div className={cn(
                    "w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 mt-0.5",
                    item.done ? "bg-green-500 border-green-500" : "border-border"
                  )}>
                    {item.done && <span className="text-[9px] text-white font-bold">✓</span>}
                  </div>
                  <span className={cn(
                    "text-xs leading-relaxed",
                    item.done ? "line-through text-muted-foreground" : "text-foreground"
                  )}>
                    {item.item}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Output */}
        {task.output && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Output</p>
            <div className="rounded-lg border border-border bg-accent/20 p-3 max-h-40 overflow-y-auto">
              <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap font-mono">{task.output}</p>
            </div>
          </div>
        )}

        {/* Sub-tasks */}
        {children.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Sub-tasks ({children.length})
            </p>
            <div className="space-y-1">
              {children.map((child) => {
                const childCfg = FLOW_STATUS[child.status] ?? FLOW_STATUS.pending;
                return (
                  <button
                    key={child.id}
                    onClick={() => onSelectTask(child)}
                    className="flex items-center gap-2 w-full px-2.5 py-2 rounded-lg border border-border hover:bg-accent hover:border-primary/30 transition-colors text-left group"
                  >
                    <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", childCfg.dot)} />
                    <span className="text-xs text-foreground flex-1 truncate group-hover:text-primary transition-colors">
                      {child.title}
                    </span>
                    <ChevronRight className="w-3 h-3 text-muted-foreground group-hover:text-primary transition-colors shrink-0" />
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Queued / pending — no sub-chat yet */}
        {!task.sub_chat_id && (task.status === "queued" || task.status === "pending") && (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin shrink-0" />
              <span className="text-xs text-blue-300 font-medium">
                {task.status === "queued" ? "Waiting for an agent slot" : "Pending dispatch"}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {task.status === "queued"
                ? "This task is queued and will start once a concurrency slot opens up."
                : "This task is waiting to be dispatched to an agent."}
            </p>
            {task.assigned_agent_id && (
              <button
                onClick={() => router.push(`/agents/${task.assigned_agent_id}`)}
                className="flex items-center gap-1.5 text-[11px] text-blue-400 hover:text-blue-300 transition-colors"
              >
                <SlidersHorizontal className="w-3 h-3 shrink-0" />
                Adjust concurrency limits
                <ExternalLink className="w-2.5 h-2.5 shrink-0" />
              </button>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
