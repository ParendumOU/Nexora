"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { logsApi } from "@/lib/api";
import { Terminal, ChevronDown, ChevronRight, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LogEntry {
  id: string;
  chat_id: string;
  task_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  data: Record<string, unknown> | null;
  created_at: string;
}

// ── Level styling ─────────────────────────────────────────────────────────────

const LEVEL_CLASS: Record<string, string> = {
  debug: "text-muted-foreground",
  info:  "text-blue-300",
  warn:  "text-yellow-400",
  error: "text-red-400",
};

const LEVEL_BADGE: Record<string, string> = {
  debug: "bg-muted/60 text-muted-foreground",
  info:  "bg-blue-500/10 text-blue-300",
  warn:  "bg-yellow-500/10 text-yellow-400",
  error: "bg-red-500/10 text-red-400",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ── Single log row ────────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(false);
  const hasData = entry.data && Object.keys(entry.data).length > 0;

  return (
    <div
      className={cn(
        "group flex items-start gap-2 px-3 py-1 hover:bg-accent/20 transition-colors font-mono text-[11px] leading-relaxed",
        hasData && "cursor-pointer"
      )}
      onClick={() => hasData && setOpen((v) => !v)}
    >
      <span className="text-muted-foreground/50 shrink-0 select-none">{formatTime(entry.created_at)}</span>
      <span className={cn("px-1 rounded text-[10px] font-bold shrink-0 uppercase", LEVEL_BADGE[entry.level])}>
        {entry.level}
      </span>
      <span className={cn("flex-1 break-all", LEVEL_CLASS[entry.level])}>{entry.message}</span>
      {hasData && (
        <ChevronDown className={cn("w-3 h-3 text-muted-foreground/40 shrink-0 mt-0.5 transition-transform", open && "rotate-180")} />
      )}
      {open && hasData && (
        <div className="col-span-full w-full mt-1 ml-0 pl-2 border-l border-border text-[10px] text-muted-foreground whitespace-pre-wrap break-all">
          {JSON.stringify(entry.data, null, 2)}
        </div>
      )}
    </div>
  );
}

// ── Agent log group ───────────────────────────────────────────────────────────

function AgentGroup({ name, logs }: { name: string; logs: LogEntry[] }) {
  const [open, setOpen] = useState(true);
  const errorCount = logs.filter((l) => l.level === "error").length;
  const warnCount = logs.filter((l) => l.level === "warn").length;

  return (
    <div className="border-b border-border">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-accent/30 transition-colors text-left"
      >
        {open
          ? <ChevronDown className="w-3 h-3 text-muted-foreground" />
          : <ChevronRight className="w-3 h-3 text-muted-foreground" />
        }
        <span className="text-xs font-semibold flex-1">{name}</span>
        <span className="text-[10px] text-muted-foreground">{logs.length}</span>
        {errorCount > 0 && (
          <span className="text-[10px] bg-red-500/10 text-red-400 px-1.5 py-0.5 rounded">{errorCount} err</span>
        )}
        {warnCount > 0 && !errorCount && (
          <span className="text-[10px] bg-yellow-500/10 text-yellow-400 px-1.5 py-0.5 rounded">{warnCount} warn</span>
        )}
      </button>
      {open && (
        <div className="bg-neutral-950/50 pb-1">
          {logs.map((entry) => (
            <LogRow key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main LogPanel ─────────────────────────────────────────────────────────────

export function LogPanel({
  chatId,
  liveEntries,
  onClose,
}: {
  chatId: string;
  liveEntries: LogEntry[];
  onClose: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: historical = [] } = useQuery({
    queryKey: ["logs", chatId],
    queryFn: () => logsApi.list(chatId).then((r) => (r.data as LogEntry[]).reverse()),
  });

  // Merge historical + live, deduplicate by id
  const allLogs: LogEntry[] = [...historical];
  for (const entry of liveEntries) {
    if (!allLogs.find((l) => l.id === entry.id)) {
      allLogs.push(entry);
    }
  }

  // Group by agent_name
  const groups = allLogs.reduce<Record<string, LogEntry[]>>((acc, l) => {
    const key = l.agent_name ?? "System";
    if (!acc[key]) acc[key] = [];
    acc[key].push(l);
    return acc;
  }, {});

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allLogs.length]);

  return (
    <div className="flex flex-col h-full w-96 border-l border-border bg-card shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Agent Logs</span>
          {allLogs.length > 0 && (
            <span className="text-[10px] bg-accent px-1.5 py-0.5 rounded font-mono text-muted-foreground">
              {allLogs.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <XCircle className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Log groups */}
      {allLogs.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-center px-6">
          <Terminal className="w-6 h-6 text-muted-foreground/40" />
          <p className="text-xs text-muted-foreground">No logs yet</p>
          <p className="text-[11px] text-muted-foreground/60">
            Agent activity will stream here in real-time
          </p>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="bg-neutral-950/30">
            {Object.entries(groups).map(([name, logs]) => (
              <AgentGroup key={name} name={name} logs={logs} />
            ))}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
