"use client";
import { useMemo, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, GitBranch, Clock } from "lucide-react";
import { tasksApi, chatsApi } from "@/lib/api";
import { truncate } from "@/lib/utils";

interface ActiveTask {
  id: string;
  chat_id: string;
  chat_title: string | null;
  title: string;
  status: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  created_at: string;
}

interface ChatStats { subchat_count: number; }
interface Chat { id: string; stats?: ChatStats | null; }

export interface AgentFilterPayload {
  agentId: string;
  agentName: string;
  chatIds: string[];
}

function useElapsed(createdAt: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(t);
  }, []);
  const s = Math.floor((now - new Date(createdAt).getTime()) / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function AgentWorkflowRow({
  task,
  subAgentCount,
  taskCount,
  onClick,
}: {
  task: ActiveTask;
  subAgentCount: number;
  taskCount: number;
  onClick: () => void;
}) {
  const elapsed = useElapsed(task.created_at);
  return (
    <button
      onClick={onClick}
      className="w-full text-left flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-sidebar-accent/60 transition-colors border border-cyan-500/10 hover:border-cyan-500/25 bg-cyan-950/[0.04]"
    >
      <div className="relative shrink-0 mt-0.5">
        <div className="w-6 h-6 rounded-lg bg-cyan-950/40 border border-cyan-500/30 flex items-center justify-center">
          <Bot className="w-3 h-3 text-cyan-400" />
        </div>
        <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse border border-background" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-sidebar-foreground truncate">
          {truncate(task.assigned_agent_name ?? "Agent", 20)}
        </div>
        <div className="text-[10px] text-muted-foreground truncate mt-0.5">
          {truncate(task.title, 30)}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[9px] text-cyan-400/80 flex items-center gap-0.5">
            <Clock className="w-2 h-2" />
            {elapsed}
          </span>
          {subAgentCount > 0 && (
            <span className="text-[9px] text-muted-foreground/70 flex items-center gap-0.5">
              <GitBranch className="w-2 h-2" />
              {subAgentCount} sub
            </span>
          )}
          {taskCount > 1 && (
            <span className="text-[9px] text-muted-foreground/50">
              +{taskCount - 1} task{taskCount - 1 !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>
      <span className="text-[9px] text-cyan-400/50 shrink-0 mt-0.5 self-center">→</span>
    </button>
  );
}

export function ActiveAgentsPanel({
  onSelectAgent,
}: {
  onSelectAgent: (payload: AgentFilterPayload) => void;
}) {
  const { data: allTasks = [] } = useQuery<ActiveTask[]>({
    queryKey: ["tasks-global"],
    queryFn: () => tasksApi.listAll().then((r) => r.data as ActiveTask[]),
    refetchInterval: 3000,
  });

  const { data: chats = [] } = useQuery<Chat[]>({
    queryKey: ["chats"],
    queryFn: () => chatsApi.list().then((r) => r.data),
    staleTime: 2000,
  });

  const chatStatsMap = useMemo(
    () => new Map(chats.map((c) => [c.id, c.stats])),
    [chats]
  );

  // Group all in_progress tasks by agent
  const agentGroups = useMemo(() => {
    const byAgent = new Map<string, { representative: ActiveTask; chatIds: Set<string>; count: number }>();
    for (const t of allTasks) {
      if (t.status !== "in_progress" || !t.assigned_agent_id) continue;
      const existing = byAgent.get(t.assigned_agent_id);
      if (!existing) {
        byAgent.set(t.assigned_agent_id, { representative: t, chatIds: new Set([t.chat_id]), count: 1 });
      } else {
        existing.chatIds.add(t.chat_id);
        existing.count++;
        // keep most recent as representative
        if (new Date(t.created_at) > new Date(existing.representative.created_at)) {
          existing.representative = t;
        }
      }
    }
    return Array.from(byAgent.values());
  }, [allTasks]);

  if (agentGroups.length === 0) return null;

  return (
    <div className="border-t border-sidebar-border mt-2 pt-2 px-2 pb-2">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse shrink-0" />
        <span className="text-[10px] font-semibold text-cyan-400 uppercase tracking-wide">
          Active agents
        </span>
        <span className="text-[10px] text-muted-foreground ml-auto">
          {agentGroups.length} working
        </span>
      </div>
      <div className="space-y-1.5">
        {agentGroups.map(({ representative: task, chatIds, count }) => {
          const stats = chatStatsMap.get(task.chat_id);
          return (
            <AgentWorkflowRow
              key={task.assigned_agent_id}
              task={task}
              subAgentCount={stats?.subchat_count ?? 0}
              taskCount={count}
              onClick={() =>
                onSelectAgent({
                  agentId: task.assigned_agent_id!,
                  agentName: task.assigned_agent_name ?? "Agent",
                  chatIds: Array.from(chatIds),
                })
              }
            />
          );
        })}
      </div>
      <p className="text-[9px] text-muted-foreground/40 text-center mt-2 leading-tight">
        Click an agent to filter chats
      </p>
    </div>
  );
}
