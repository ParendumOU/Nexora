"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { tasksApi } from "@/lib/api";
import { Loader2, ListTodo, FolderKanban, Bot, ChevronDown, ChevronRight, ExternalLink, ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";

const PAGE_SIZE = 10;
const UNPAGINATED_STATUSES = new Set(["in_progress", "running"]);

interface GlobalTask {
  id: string;
  chat_id: string;
  chat_title: string | null;
  project_id: string | null;
  project_name: string | null;
  parent_id: string | null;
  title: string;
  description: string | null;
  status: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  sub_chat_id: string | null;
  checklist: Array<{ id: string; item: string; done: boolean }>;
  created_at: string;
  completed_at: string | null;
}

const STATUS_DOT: Record<string, string> = {
  pending:     "bg-yellow-400",
  in_progress: "bg-cyan-400 animate-pulse",
  running:     "bg-cyan-400 animate-pulse",
  paused:      "bg-orange-400",
  queued:      "bg-blue-400",
  completed:   "bg-green-400",
  failed:      "bg-red-400",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending", in_progress: "Running", running: "Running",
  paused: "Paused", queued: "Queued", completed: "Done", failed: "Failed",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  pending:     "bg-yellow-400/10 text-yellow-400 border-yellow-400/20",
  in_progress: "bg-cyan-400/10 text-cyan-400 border-cyan-400/20",
  running:     "bg-cyan-400/10 text-cyan-400 border-cyan-400/20",
  paused:      "bg-orange-400/10 text-orange-400 border-orange-400/20",
  queued:      "bg-blue-400/10 text-blue-400 border-blue-400/20",
  completed:   "bg-green-400/10 text-green-400 border-green-400/20",
  failed:      "bg-red-400/10 text-red-400 border-red-400/20",
};

function GroupHeader({ label, count, active, onClick }: {
  label: string; count: number; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 w-full text-left px-4 py-2.5 bg-accent/30 hover:bg-accent/50 border-b border-border transition-colors"
    >
      {active ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />}
      <span className={cn("w-2 h-2 rounded-full shrink-0", STATUS_DOT[label] ?? "bg-muted-foreground")} />
      <span className="text-xs font-semibold">{STATUS_LABEL[label] ?? label}</span>
      <span className="text-[10px] text-muted-foreground ml-1">{count}</span>
    </button>
  );
}

export default function GlobalTasksPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<"all" | "mine">("all");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set(["completed"]));
  const [pages, setPages] = useState<Record<string, number>>({});

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ["tasks-global"],
    queryFn: () => tasksApi.listAll().then((r) => r.data as GlobalTask[]),
    refetchInterval: 5000,
  });

  const grouped = tasks.reduce<Record<string, GlobalTask[]>>((acc, t) => {
    const key = t.status;
    if (!acc[key]) acc[key] = [];
    acc[key].push(t);
    return acc;
  }, {});

  const statusOrder = ["in_progress", "running", "paused", "queued", "pending", "failed", "completed"];
  const sortedStatuses = statusOrder.filter((s) => grouped[s]?.length);

  const toggleCollapse = (status: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(status)) {
        next.delete(status);
      } else {
        next.add(status);
        setPage(status, 0);
      }
      return next;
    });

  const getPage = (status: string) => pages[status] ?? 0;
  const setPage = (status: string, page: number) =>
    setPages((prev) => ({ ...prev, [status]: page }));

  const totalActive = tasks.filter((t) => ["in_progress", "running", "paused", "queued"].includes(t.status)).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <ListTodo className="w-5 h-5" />
            All Tasks
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {tasks.length} total · {totalActive} active
          </p>
        </div>
        <div className="flex items-center gap-1 p-0.5 bg-accent/30 rounded-lg border border-border">
          {(["all", "mine"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setFilter(v)}
              className={cn(
                "px-3 py-1 text-xs rounded-md transition-colors capitalize",
                filter === v ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center space-y-3">
            <ListTodo className="w-10 h-10 text-muted-foreground/40" />
            <div>
              <p className="font-medium">No tasks yet</p>
              <p className="text-sm text-muted-foreground">Tasks appear here when agents start working</p>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {sortedStatuses.map((status) => (
              <div key={status}>
                <GroupHeader
                  label={status}
                  count={grouped[status].length}
                  active={!collapsed.has(status)}
                  onClick={() => toggleCollapse(status)}
                />
                {!collapsed.has(status) && (() => {
                  const all = grouped[status];
                  const paginated = !UNPAGINATED_STATUSES.has(status);
                  const page = getPage(status);
                  const totalPages = paginated ? Math.ceil(all.length / PAGE_SIZE) : 1;
                  const visible = paginated ? all.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) : all;
                  return (
                    <div>
                      <div className="divide-y divide-border/50">
                        {visible.map((task) => (
                          <div
                            key={task.id}
                            className="flex items-start gap-3 px-4 py-3 hover:bg-accent/30 transition-colors cursor-pointer group"
                            onClick={() => router.push(`/chat/${task.sub_chat_id ?? task.chat_id}`)}
                          >
                            <span className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0", STATUS_DOT[task.status])} />

                            <div className="flex-1 min-w-0 space-y-1">
                              <div className="flex items-start gap-2">
                                <span className="text-sm font-medium leading-tight">{task.title}</span>
                                <span
                                  className={cn(
                                    "shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium",
                                    STATUS_BADGE_CLASS[task.status]
                                  )}
                                >
                                  {STATUS_LABEL[task.status]}
                                </span>
                              </div>

                              <div className="flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
                                {task.project_name && (
                                  <span className="flex items-center gap-1">
                                    <FolderKanban className="w-3 h-3" />
                                    {task.project_name}
                                  </span>
                                )}
                                {task.chat_title && (
                                  <span className="flex items-center gap-1 text-muted-foreground/70">
                                    {task.chat_title}
                                  </span>
                                )}
                                {task.assigned_agent_name && (
                                  <span className="flex items-center gap-1 text-cyan-400/80">
                                    <Bot className="w-3 h-3" />
                                    {task.assigned_agent_name}
                                  </span>
                                )}
                                {task.checklist.length > 0 && (
                                  <span className="text-muted-foreground/60">
                                    {task.checklist.filter((c) => c.done).length}/{task.checklist.length} checks
                                  </span>
                                )}
                              </div>
                            </div>

                            <ExternalLink className="w-3.5 h-3.5 text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-opacity mt-0.5 shrink-0" />
                          </div>
                        ))}
                      </div>
                      {paginated && totalPages > 1 && (
                        <div className="flex items-center justify-between px-4 py-2 border-t border-border/50 bg-accent/10">
                          <button
                            disabled={page === 0}
                            onClick={() => setPage(status, page - 1)}
                            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none transition-colors"
                          >
                            <ChevronLeft className="w-3 h-3" /> Prev
                          </button>
                          <span className="text-[11px] text-muted-foreground">
                            {page + 1} / {totalPages}
                          </span>
                          <button
                            disabled={page >= totalPages - 1}
                            onClick={() => setPage(status, page + 1)}
                            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none transition-colors"
                          >
                            Next <ChevronRight className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
