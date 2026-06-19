"use client";
import { useState, useEffect } from "react";
import { Bot, Clock } from "lucide-react";

export interface ActiveTask {
  id: string;
  chat_id: string;
  chat_title: string | null;
  title: string;
  status: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  created_at: string;
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

function ActiveTaskCard({ task }: { task: ActiveTask }) {
  const elapsed = useElapsed(task.created_at);
  return (
    <div className="flex items-start gap-2.5 bg-card border border-cyan-500/20 rounded-xl px-3 py-2.5 min-w-[180px] max-w-[260px]">
      <div className="relative shrink-0">
        <div className="w-7 h-7 rounded-lg bg-cyan-950/40 border border-cyan-500/30 flex items-center justify-center">
          <Bot className="w-3.5 h-3.5 text-cyan-400" />
        </div>
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-cyan-400 animate-pulse border-2 border-background" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold text-foreground truncate">{task.assigned_agent_name ?? "Agent"}</div>
        <div className="text-[11px] text-muted-foreground truncate mt-0.5">{task.title}</div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-[10px] text-cyan-400/80 flex items-center gap-1">
            <Clock className="w-2.5 h-2.5" />{elapsed}
          </span>
          {task.chat_title && (
            <span className="text-[10px] text-muted-foreground/60 truncate max-w-[110px]">{task.chat_title}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export function ActiveAgentsStrip({ activeTasks, onNavigate }: { activeTasks: ActiveTask[]; onNavigate: (chatId: string) => void }) {
  if (activeTasks.length === 0) return null;

  const uniqueAgents = new Set(activeTasks.map((t) => t.assigned_agent_id)).size;

  return (
    <div className="border-b border-cyan-500/15 bg-cyan-950/[0.07] shrink-0">
      <div className="px-5 pt-2.5 pb-1 flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
        <span className="text-[11px] font-semibold text-cyan-400 uppercase tracking-wide">
          Active Now
        </span>
        <span className="text-[11px] text-muted-foreground">
          · {uniqueAgents} agent{uniqueAgents !== 1 ? "s" : ""}, {activeTasks.length} task{activeTasks.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="px-5 pb-3 flex gap-2 overflow-x-auto">
        {activeTasks.map((t) => (
          <button key={t.id} onClick={() => onNavigate(t.chat_id)} className="text-left shrink-0">
            <ActiveTaskCard task={t} />
          </button>
        ))}
      </div>
    </div>
  );
}
