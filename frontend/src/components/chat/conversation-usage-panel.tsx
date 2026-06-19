"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, ArrowDown, ArrowUp, Wrench, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { chatsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ToolCall {
  args: Record<string, unknown>;
}

interface ToolEntry {
  name: string;
  count: number;
  calls: ToolCall[];
}

interface UsageData {
  input_tokens: number;
  output_tokens: number;
  tool_calls: number;
  by_provider: Array<{
    provider: string;
    input_tokens: number;
    output_tokens: number;
  }>;
  by_tool: ToolEntry[];
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtToolName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function ArgValue({ value }: { value: unknown }) {
  if (typeof value === "string") {
    if (value.length > 200) {
      return <TruncatedText text={value} />;
    }
    return <span className="text-green-400/90 break-all">&quot;{value}&quot;</span>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="text-blue-400/90">{String(value)}</span>;
  }
  if (value === null) {
    return <span className="text-muted-foreground/60">null</span>;
  }
  if (Array.isArray(value)) {
    return (
      <span className="text-muted-foreground">
        [{value.map((v, i) => <span key={i}><ArgValue value={v} />{i < value.length - 1 ? ", " : ""}</span>)}]
      </span>
    );
  }
  if (typeof value === "object") {
    return (
      <span className="text-muted-foreground">
        {"{"}
        {Object.entries(value as Record<string, unknown>).map(([k, v], i, arr) => (
          <span key={k}>
            <span className="text-yellow-400/80">{k}</span>: <ArgValue value={v} />
            {i < arr.length - 1 ? ", " : ""}
          </span>
        ))}
        {"}"}
      </span>
    );
  }
  return <span>{String(value)}</span>;
}

function TruncatedText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <span>
      <span className="text-green-400/90 break-all">&quot;{expanded ? text : text.slice(0, 200)}…&quot;</span>
      <button
        onClick={() => setExpanded(e => !e)}
        className="ml-1 text-[9px] text-primary/70 hover:text-primary underline"
      >
        {expanded ? "less" : `+${text.length - 200} more`}
      </button>
    </span>
  );
}

function ToolCallRow({ call, index }: { call: ToolCall; index: number }) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(call.args);
  return (
    <div className="border border-border/40 rounded-md overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 w-full px-2 py-1.5 text-left hover:bg-accent/40 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 shrink-0 text-muted-foreground" />}
        <span className="text-[10px] text-muted-foreground">Call #{index + 1}</span>
        {!open && entries.length > 0 && (
          <span className="text-[10px] text-muted-foreground/60 truncate ml-auto max-w-[140px]">
            {entries[0][0]}: {typeof entries[0][1] === "string" ? `"${String(entries[0][1]).slice(0, 30)}"` : String(entries[0][1])}
          </span>
        )}
      </button>
      {open && (
        <div className="px-2 pb-2 pt-0.5 font-mono text-[10px] space-y-0.5 bg-background/40">
          {entries.length === 0 ? (
            <span className="text-muted-foreground/60">(no args)</span>
          ) : entries.map(([k, v]) => (
            <div key={k} className="flex gap-1.5 flex-wrap">
              <span className="text-yellow-400/80 shrink-0">{k}:</span>
              <ArgValue value={v} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolEntryRow({ entry }: { entry: ToolEntry }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border/60 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full px-2.5 py-2 hover:bg-accent/30 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 shrink-0 text-muted-foreground" />}
        <span className="text-[11px] font-medium text-foreground flex-1 text-left">{fmtToolName(entry.name)}</span>
        <span className="text-[10px] font-mono text-primary/80 bg-primary/10 rounded px-1.5 py-0.5">{entry.count}×</span>
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1.5 bg-background/30">
          {entry.calls.map((call, i) => (
            <ToolCallRow key={i} call={call} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ConversationUsagePanel({ chatId, isStreaming, onClose }: { chatId: string; isStreaming?: boolean; onClose: () => void }) {
  const { data, isLoading } = useQuery<UsageData>({
    queryKey: ["chat-usage", chatId],
    queryFn: () => chatsApi.usage(chatId).then((r) => r.data),
    refetchInterval: isStreaming ? 3000 : false,
  });

  const total = data ? data.input_tokens + data.output_tokens : 0;

  return (
    <div className="flex flex-col h-full w-72 border-l border-border bg-card shrink-0 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <span className="text-xs font-semibold">Conversation stats</span>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center flex-1">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : data ? (
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {/* Token cards */}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border bg-background p-3">
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground mb-1">
                <ArrowDown className="w-3 h-3 text-blue-400" /> Input
              </div>
              <div className="text-lg font-semibold tabular-nums">{fmt(data.input_tokens)}</div>
              <div className="text-[10px] text-muted-foreground">tokens</div>
            </div>
            <div className="rounded-lg border border-border bg-background p-3">
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground mb-1">
                <ArrowUp className="w-3 h-3 text-green-400" /> Output
              </div>
              <div className="text-lg font-semibold tabular-nums">{fmt(data.output_tokens)}</div>
              <div className="text-[10px] text-muted-foreground">tokens</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border bg-background p-3 col-span-2">
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground mb-1">
                <Wrench className="w-3 h-3 text-orange-400" /> Tool calls
              </div>
              <div className="text-lg font-semibold tabular-nums">{data.tool_calls.toLocaleString()}</div>
            </div>
          </div>

          {/* Token split */}
          {total > 0 && (
            <div>
              <div className="text-[10px] text-muted-foreground mb-1.5">Token split</div>
              <div className="flex h-2 rounded-full overflow-hidden">
                <div className="bg-blue-400/80 transition-all" style={{ width: `${(data.input_tokens / total) * 100}%` }} />
                <div className="bg-green-400/80 flex-1" />
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                <span>{Math.round((data.input_tokens / total) * 100)}% input</span>
                <span>{Math.round((data.output_tokens / total) * 100)}% output</span>
              </div>
            </div>
          )}

          {/* By provider */}
          {data.by_provider.length > 0 && (
            <div>
              <div className="text-[10px] text-muted-foreground mb-2">By provider</div>
              <div className="space-y-2">
                {data.by_provider.map((p) => {
                  const provTotal = p.input_tokens + p.output_tokens;
                  const pct = total > 0 ? (provTotal / total) * 100 : 100;
                  return (
                    <div key={p.provider}>
                      <div className="flex justify-between text-[10px] mb-1">
                        <span className="text-foreground font-medium truncate max-w-[140px]">{p.provider}</span>
                        <span className="text-muted-foreground tabular-nums">{fmt(provTotal)}</span>
                      </div>
                      <div className="h-1 rounded-full bg-muted overflow-hidden">
                        <div className="h-full bg-primary/60 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* By tool */}
          {data.by_tool && data.by_tool.length > 0 && (
            <div>
              <div className="text-[10px] text-muted-foreground mb-2">Tool calls</div>
              <div className="space-y-1.5">
                {data.by_tool.map((entry) => (
                  <ToolEntryRow key={entry.name} entry={entry} />
                ))}
              </div>
            </div>
          )}

          {total === 0 && (
            <p className="text-[11px] text-muted-foreground text-center py-4">
              No token data recorded yet — usage is tracked for Claude, Gemini, and OpenAI-compatible streams.
            </p>
          )}
        </div>
      ) : (
        <div className="flex items-center justify-center flex-1 text-xs text-muted-foreground">
          Failed to load stats
        </div>
      )}
    </div>
  );
}
