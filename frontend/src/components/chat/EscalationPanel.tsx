"use client";

import { useEffect, useState } from "react";
import { MessageSquare, ArrowRight, Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";

interface AgentMessage {
  id: string;
  from_agent_id: string;
  from_agent_name: string | null;
  to_agent_id: string;
  to_agent_name: string | null;
  chat_id: string;
  task_id: string | null;
  subject: string;
  body: string;
  reply_to_id: string | null;
  reply_body: string | null;
  status: "pending" | "delivered" | "replied" | "timeout";
  mode: "sync" | "async";
  created_at: string;
  delivered_at: string | null;
  replied_at: string | null;
}

const STATUS_ICON: Record<AgentMessage["status"], React.ReactNode> = {
  pending:   <Loader2 className="w-3.5 h-3.5 text-yellow-400 animate-spin" />,
  delivered: <Clock className="w-3.5 h-3.5 text-blue-400" />,
  replied:   <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  timeout:   <XCircle className="w-3.5 h-3.5 text-red-400" />,
};

const STATUS_LABEL: Record<AgentMessage["status"], string> = {
  pending:   "pending",
  delivered: "waiting",
  replied:   "replied",
  timeout:   "timeout",
};

const STATUS_COLOR: Record<AgentMessage["status"], string> = {
  pending:   "text-yellow-400",
  delivered: "text-blue-400",
  replied:   "text-emerald-400",
  timeout:   "text-red-400",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function MessageRow({ msg }: { msg: AgentMessage }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="group border-b border-border/40 last:border-0 cursor-pointer hover:bg-accent/10 transition-colors"
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
          {STATUS_ICON[msg.status]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-medium text-foreground truncate max-w-[120px]">
              {msg.from_agent_name ?? msg.from_agent_id.slice(0, 8)}
            </span>
            <ArrowRight className="w-3 h-3 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium text-foreground truncate max-w-[120px]">
              {msg.to_agent_name ?? msg.to_agent_id.slice(0, 8)}
            </span>
            <span className={cn("text-[10px] ml-auto shrink-0", STATUS_COLOR[msg.status])}>
              {STATUS_LABEL[msg.status]}
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground truncate mt-0.5">{msg.subject}</p>
          <span className="text-[10px] text-muted-foreground/50">{formatTime(msg.created_at)}</span>
        </div>
      </div>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <div className="rounded bg-muted/30 p-2 text-[11px] text-muted-foreground whitespace-pre-wrap break-words border border-border/30">
            {msg.body}
          </div>
          {msg.reply_body && (
            <div className="rounded bg-emerald-500/5 border border-emerald-500/20 p-2 text-[11px] text-emerald-300 whitespace-pre-wrap break-words">
              <span className="block text-[10px] text-emerald-500/60 mb-1 font-medium uppercase tracking-wide">Reply</span>
              {msg.reply_body}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface EscalationPanelProps {
  chatId: string;
  liveMessages?: AgentMessage[];
}

export function EscalationPanel({ chatId, liveMessages = [] }: EscalationPanelProps) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`/api/agent-messages/chat/${chatId}`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled) setMessages(data);
      } catch {
        // silent fail — panel degrades gracefully
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [chatId]);

  // Merge live websocket messages on top of fetched ones
  useEffect(() => {
    if (!liveMessages.length) return;
    setMessages((prev) => {
      const ids = new Set(prev.map((m) => m.id));
      const next = [...prev];
      for (const m of liveMessages) {
        if (ids.has(m.id)) {
          const idx = next.findIndex((x) => x.id === m.id);
          if (idx >= 0) next[idx] = m;
        } else {
          next.push(m);
        }
      }
      return next;
    });
  }, [liveMessages]);

  const all = messages.sort((a, b) => a.created_at.localeCompare(b.created_at));
  const topLevel = all.filter((m) => !m.reply_to_id);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/60 shrink-0">
        <MessageSquare className="w-4 h-4 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground">Agent Messages</span>
        {topLevel.length > 0 && (
          <span className="ml-auto text-[10px] text-muted-foreground/60 tabular-nums">
            {topLevel.length} message{topLevel.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      <ScrollArea className="flex-1">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 text-muted-foreground animate-spin" />
          </div>
        ) : topLevel.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center px-4">
            <MessageSquare className="w-6 h-6 text-muted-foreground/30" />
            <p className="text-[11px] text-muted-foreground/50">
              No inter-agent messages yet. Agents will appear here when they communicate directly.
            </p>
          </div>
        ) : (
          <div>
            {topLevel.map((msg) => (
              <MessageRow key={msg.id} msg={msg} />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
