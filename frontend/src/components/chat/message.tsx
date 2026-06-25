"use client";
import { useState, useRef, useEffect, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Bot, Copy, Check, ChevronDown, ChevronRight, Pencil, X, SendHorizonal, EyeOff, Eye, Briefcase, AlertTriangle, CornerDownRight, Brain } from "lucide-react";
import { cn, copyToClipboard } from "@/lib/utils";

interface UsageMeta {
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  reasoning_output_tokens?: number;
}

interface MessageMeta {
  provider?: string;
  model?: string;
  usage?: UsageMeta;
  cost_usd?: number;
  duration_ms?: number;
  session_id?: string;
  thread_id?: string;
  kind?: "task_brief" | "task_error" | "tool_result_injection" | "child_task_injection" | "nudge";
  from_agent_id?: string | null;
  tg_user_display?: string;
  error?: boolean;
}

interface MessageProps {
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  providerUsed?: string;
  agentName?: string | null;
  userName?: string | null;
  avatarEmoji?: string;
  metadata?: MessageMeta;
  userId?: string | null;
  currentUserId?: string | null;
  messageId?: string;
  excluded?: boolean;
  isContinuation?: boolean;
  createdAt?: string;
  subordinateAgentName?: string | null;
  onEditSubmit?: (messageId: string, newContent: string) => void;
  onExcludedToggle?: (messageId: string, excluded: boolean) => void;
}

function completeStreamingMarkdown(raw: string): string {
  let s = raw;
  // Close open fenced code blocks (they suppress inline parsing inside)
  const fences = (s.match(/^```/gm) || []).length;
  if (fences % 2 !== 0) return s + "\n```";
  // Strip completed code blocks before counting inline markers
  const noFences = s.replace(/```[\s\S]*?```/g, "");
  // Close open inline code
  if ((noFences.match(/`/g) || []).length % 2 !== 0) s += "`";
  // Close open bold
  if ((noFences.match(/\*\*/g) || []).length % 2 !== 0) s += "**";
  return s;
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative group rounded-lg overflow-hidden bg-[#0d1117] border border-border my-3">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-[#161b22]">
        <span className="text-[10px] font-mono text-muted-foreground">{language || "code"}</span>
        <button
          onClick={() => { copyToClipboard(code); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          {copied ? <><Check className="w-3 h-3 text-green-400" />Copied</> : <><Copy className="w-3 h-3" />Copy</>}
        </button>
      </div>
      <pre className="p-4 overflow-x-auto text-sm font-mono text-[#e6edf3] leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

const SHELL_TOOLS = new Set(["shell_run", "run_shell", "bash", "execute_shell", "run_command"]);

function ToolResultItem({ toolName, data }: { toolName: string; data: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);

  if (SHELL_TOOLS.has(toolName)) {
    const exitCode = data.exit_code as number ?? 0;
    const output = (data.output as string) || (data.stdout as string) || "";
    const stderr = (data.stderr as string) || "";
    const displayOutput = output || stderr || "(no output)";
    const success = exitCode === 0;
    const firstLine = displayOutput.split("\n")[0].slice(0, 70);

    return (
      <div className="my-1">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-card/50 hover:bg-card transition-colors text-left"
        >
          <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground transition-transform shrink-0", expanded && "rotate-180")} />
          <span className="text-xs font-mono text-muted-foreground shrink-0">{toolName}</span>
          <span className={cn(
            "text-[10px] font-mono px-1.5 py-0.5 rounded border shrink-0",
            success
              ? "bg-green-500/10 text-green-400 border-green-500/20"
              : "bg-red-500/10 text-red-400 border-red-500/20"
          )}>
            exit&nbsp;{exitCode}
          </span>
          {!expanded && (
            <span className="text-[10px] text-muted-foreground truncate flex-1">{firstLine}</span>
          )}
        </button>

        {expanded && (
          <div className="mt-1 ml-4 rounded-lg overflow-hidden border border-border">
            <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-[#161b22]">
              <span className="text-[10px] font-mono text-muted-foreground">output</span>
              <span className={cn("text-[10px] font-mono", success ? "text-green-400" : "text-red-400")}>
                exit_code: {exitCode}
              </span>
            </div>
            <pre className="p-3 bg-[#0d1117] text-[11px] font-mono text-[#e6edf3] leading-relaxed whitespace-pre-wrap break-all max-h-64 overflow-y-auto">
              {displayOutput}
            </pre>
          </div>
        )}
      </div>
    );
  }

  const PRIORITY = ["title", "name", "status", "id", "assigned_agent", "agent_name", "description"];
  const entries = Object.entries(data);
  const sorted = [
    ...entries.filter(([k]) => PRIORITY.includes(k)),
    ...entries.filter(([k]) => !PRIORITY.includes(k)),
  ];
  const preview = sorted.slice(0, 2).map(([k, v]) => {
    const s = typeof v === "object" ? JSON.stringify(v) : String(v);
    return `${k}: ${s.slice(0, 50)}`;
  }).join("  ·  ");

  return (
    <div className="my-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-card/50 hover:bg-card transition-colors text-left"
      >
        <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground transition-transform shrink-0", expanded && "rotate-180")} />
        <div className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" />
        <span className="text-xs font-mono text-foreground shrink-0">{toolName}</span>
        {!expanded && preview && (
          <span className="text-[10px] text-muted-foreground truncate flex-1">{preview}</span>
        )}
        <span className="text-[10px] text-muted-foreground bg-accent px-1.5 py-0.5 rounded shrink-0">
          {entries.length} fields
        </span>
      </button>

      {expanded && (
        <div className="mt-1 ml-4 p-3 rounded-lg border border-border bg-card/30 space-y-1.5">
          {sorted.map(([key, value]) => {
            const s = typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
            const isLong = s.length > 200;
            return (
              <div key={key} className="flex gap-2 text-xs">
                <span className="font-mono text-muted-foreground w-32 shrink-0 truncate" title={key}>{key}:</span>
                <span className={cn("text-foreground break-all", isLong && "font-mono text-[10px] text-muted-foreground")}>
                  {isLong ? s.slice(0, 200) + "…" : s}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToolResultDisplay({ content }: { content: string }) {
  const regex = /\*\*(\w+)\*\*:\s*```json\s*([\s\S]*?)```/g;
  const matches = [...content.matchAll(regex)];

  if (matches.length === 0) {
    const stripped = content.replace(/\[Tool results[^\]]*\]/, "").trim();
    return (
      <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-all p-2 rounded border border-border bg-card/30">
        {stripped}
      </pre>
    );
  }

  return (
    <div className="space-y-0 -my-1">
      {matches.map((match, i) => {
        const [, toolName, jsonStr] = match;
        let parsed: Record<string, unknown> | null = null;
        try {
          parsed = JSON.parse(jsonStr.trim()) as Record<string, unknown>;
        } catch {
          // Try to salvage truncated JSON: extract top-level string values via regex
          const salvaged: Record<string, unknown> = {};
          for (const m of jsonStr.matchAll(/"(\w+)":\s*("(?:[^"\\]|\\.)*"|[\d.]+|true|false|null)/g)) {
            try { salvaged[m[1]] = JSON.parse(m[2]); } catch { salvaged[m[1]] = m[2]; }
          }
          if (Object.keys(salvaged).length > 0) parsed = salvaged;
        }
        if (parsed) {
          return <ToolResultItem key={i} toolName={toolName} data={parsed} />;
        }
        return (
          <div key={i} className="my-1 p-2 rounded border border-border bg-card/30">
            <span className="text-xs font-mono text-muted-foreground">{toolName}</span>
            <pre className="text-[10px] font-mono text-muted-foreground mt-1 whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
              {jsonStr.trim()}
            </pre>
          </div>
        );
      })}
    </div>
  );
}

const THINKING_RE = /<(?:thinking|think)>([\s\S]*?)<\/(?:thinking|think)>/gi;
const PROPOSAL_RE = /<proposal>([\s\S]*?)<\/proposal>/gi;

// Inside reasoning, the model often pastes tool-call JSON / fenced code. Match those
// spans so they can render as a compact chip instead of a raw JSON dump.
const TOOLCALL_IN_THOUGHT_RE =
  /```[\s\S]*?```|\[\s*\{[\s\S]*?"name"\s*:[\s\S]*?\}\s*\]|\{\s*"name"\s*:\s*"[\w-]+"[\s\S]*?\}/g;

function toolNamesIn(snippet: string): string[] {
  const names: string[] = [];
  const re = /"name"\s*:\s*"([\w-]+)"/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(snippet))) names.push(m[1]);
  return names;
}

// Replace embedded tool-call JSON / code fences inside a thought with an inline-code
// chip (`⚙ tool names`) so the reasoning renders as readable markdown instead of a
// raw JSON dump.
function toThoughtMarkdown(text: string): string {
  return text.replace(TOOLCALL_IN_THOUGHT_RE, (m) => {
    const names = toolNamesIn(m);
    return "`⚙ " + (names.length ? names.join(" · ") : "code") + "`";
  });
}

function thoughtSummary(text: string): string {
  const names = toolNamesIn(text);
  const rawFirst = (text.split("\n").find((l) => l.trim()) || "").trim();
  // Code / tool-call paragraph → chip-style summary.
  if (rawFirst.startsWith("```") || rawFirst.startsWith("[") || rawFirst.startsWith("{")) {
    return names.length ? "⚙ " + names.join(", ") : "⚙ code";
  }
  // Strip list/heading markers (leading) then markdown emphasis/code markers
  // (anywhere) so a summary like "2. **Determine the Workflow:**" reads
  // "Determine the Workflow".
  const clean = rawFirst
    .replace(/^[#>\-*\d.\s]+/, "")
    .replace(/[*`_~]+/g, "")
    .replace(/:\s*$/, "")
    .trim();
  return (clean || (names.length ? "⚙ " + names.join(", ") : "")).slice(0, 90);
}

// One reasoning paragraph ("thought"). Collapsed → first-line summary; expanded →
// full text (tool-call JSON rendered as chips). `defaultOpen` follows the live
// state — only the LATEST thought is open while thinking; past ones fold as new
// ones arrive, and everything folds once thinking finishes. A click overrides.
function ThoughtItem({ text, index, defaultOpen }: { text: string; index: number; defaultOpen: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const isOpen = open ?? defaultOpen;
  return (
    <div className="py-px">
      <button
        onClick={() => setOpen(!isOpen)}
        className="flex items-start gap-1 text-left w-full text-muted-foreground/70 hover:text-muted-foreground transition-colors"
      >
        <ChevronRight className={cn("w-3 h-3 mt-0.5 shrink-0 transition-transform", isOpen && "rotate-90")} />
        {isOpen
          ? <span className="text-[10px] uppercase tracking-wide opacity-50">Thought {index + 1}</span>
          : <span className="truncate">{thoughtSummary(text) || `Thought ${index + 1}`}</span>}
      </button>
      {isOpen && (
        <div className="pl-4 leading-relaxed text-muted-foreground prose-chat max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_code]:text-[10px]">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{toThoughtMarkdown(text)}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

function ThinkingBlock({ blocks, live }: { blocks: string[]; live?: boolean }) {
  // Expanded while the model is still thinking (no answer yet), auto-collapsed once
  // the answer streams in. A manual click takes over after. CLI-like.
  const [manual, setManual] = useState<boolean | null>(null);
  const expanded = manual ?? !!live;

  const combined = blocks.join("\n\n");
  // Each paragraph (double newline) is one "thought".
  const thoughts = useMemo(
    () => combined.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean),
    [combined],
  );

  // Auto-scroll to the latest reasoning while live, unless the user scrolled up.
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  useEffect(() => {
    if (expanded && pinnedRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [combined, expanded]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (el) pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  // Duration: start when live begins, freeze when it ends → "Thought for Ns".
  const startRef = useRef<number>(Date.now());
  const wasLive = useRef(false);
  const [elapsed, setElapsed] = useState<number | null>(null);
  useEffect(() => {
    if (live && !wasLive.current) { startRef.current = Date.now(); wasLive.current = true; }
    else if (!live && wasLive.current) {
      setElapsed(Math.max(1, Math.round((Date.now() - startRef.current) / 1000)));
      wasLive.current = false;
    }
  }, [live]);

  const label = live ? "Thinking…" : (elapsed != null ? `Thought for ${elapsed}s` : "Thought");

  // Same panel chrome as the "Agent · N actions" card: rounded-xl bordered box,
  // header (collapse + status dot + "Thought · N steps" + live label), body list.
  return (
    <div className="my-2 rounded-xl border border-border bg-muted/30 text-xs overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-inherit">
        <button
          onClick={() => setManual(!expanded)}
          className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
          aria-label={expanded ? "Collapse reasoning" : "Expand reasoning"}
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </button>
        <Brain className={cn("w-3.5 h-3.5 shrink-0", live ? "text-primary" : "text-muted-foreground")} />
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", live ? "bg-primary animate-pulse" : "bg-green-400")} />
        <span className="font-medium text-foreground">Thought</span>
        {thoughts.length > 1 && (
          <>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">{thoughts.length} steps</span>
          </>
        )}
        <span className="text-muted-foreground text-xs ml-auto">{label}</span>
      </div>
      {expanded && (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="px-3 py-2 space-y-1 bg-muted/20 text-[11px] leading-relaxed max-h-72 overflow-y-auto"
        >
          {thoughts.map((t, i) => (
            // While live, only the LATEST thought stays open; past ones fold to a
            // summary as new ones arrive. Once thinking ends, all fold (re-expandable).
            <ThoughtItem key={i} text={t} index={i} defaultOpen={!!live && i === thoughts.length - 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function formatMessageTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (isToday) return time;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + ", " + time;
}

export function ChatMessage({
  role, content, isStreaming, providerUsed, agentName, userName, avatarEmoji,
  metadata, userId, currentUserId, messageId, excluded = false,
  isContinuation = false, createdAt, subordinateAgentName,
  onEditSubmit, onExcludedToggle,
}: MessageProps) {
  // Task brief: the parent agent's directive that opens a sub-chat. Render as a
  // distinctive "manager → subordinate" card so the hierarchy is visually obvious
  // and the brief doesn't read as the sub-agent's own first message.
  if (metadata?.kind === "task_brief") {
    return (
      <div className="mx-4 my-3 rounded-xl border border-amber-500/30 bg-amber-500/5 text-xs overflow-hidden animate-fade-in">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-amber-500/20 bg-amber-500/5">
          <Briefcase className="w-3.5 h-3.5 text-amber-500 shrink-0" />
          <span className="font-medium text-foreground">{agentName || "Manager"}</span>
          <CornerDownRight className="w-3 h-3 text-muted-foreground shrink-0" />
          <span className="font-medium text-foreground">{subordinateAgentName || "Sub-agent"}</span>
          <span className="text-[10px] uppercase tracking-wide text-amber-500/80 ml-auto">Task brief</span>
        </div>
        <div className="px-4 py-3 text-sm text-foreground prose-chat">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    );
  }
  if (metadata?.error) {
    return (
      <div className="mx-4 my-3 rounded-xl border border-destructive/40 bg-destructive/5 text-xs overflow-hidden animate-fade-in">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-destructive/30">
          <AlertTriangle className="w-3.5 h-3.5 text-destructive shrink-0" />
          <span className="font-medium text-foreground">{agentName || "Agent"}</span>
          <span className="text-[10px] uppercase tracking-wide text-destructive/80 ml-auto">Failed to respond</span>
        </div>
        <div className="px-4 py-3 text-[13px] text-destructive whitespace-pre-wrap break-words">{content}</div>
      </div>
    );
  }
  if (metadata?.kind === "task_error") {
    return (
      <div className="mx-4 my-3 rounded-xl border border-destructive/40 bg-destructive/5 text-xs overflow-hidden animate-fade-in">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-destructive/30">
          <AlertTriangle className="w-3.5 h-3.5 text-destructive shrink-0" />
          <span className="font-medium text-foreground">{agentName || "Agent"}</span>
          <span className="text-[10px] uppercase tracking-wide text-destructive/80 ml-auto">Task error</span>
        </div>
        <pre className="px-4 py-3 text-[11px] font-mono text-destructive whitespace-pre-wrap break-all">{content}</pre>
      </div>
    );
  }
  const isUser = role === "user";
  const isAgent = !!agentName;
  const isCurrentUser = userId != null ? userId === currentUserId : currentUserId != null;

  const thinkingBlocks: string[] = [];
  let strippedContent = content
    .replace(THINKING_RE, (_, inner: string) => {
      thinkingBlocks.push(inner);
      return "";
    })
    // Strip proposal blocks — parsed and stored separately, not for display
    .replace(PROPOSAL_RE, "")
    // Strip internal model analysis/scratchpad tags that should not appear in output
    .replace(/<\s*(?:analysis_thought|internal_thought|scratchpad)\s*>[\s\S]*?<\s*\/\s*(?:analysis_thought|internal_thought|scratchpad)\s*>/gi, "")
    // Hide the bare `<final/>` turn-end marker — it's a structural signal for
    // the watchdog, not user-facing content.
    .replace(/<\s*final\s*\/?\s*>/gi, "")
    .replace(/<\s*final\s*>\s*<\s*\/\s*final\s*>/gi, "")
    // Strip tool_calls fences (backtick format)
    .replace(/```[ \t]*(?:tool_calls|json|tools)[ \t]*\n[\s\S]*?```/gi, "")
    .replace(/```[ \t]*\n(?:tool_calls|json|tools)\n[\s\S]*?```/gi, "")
    // Strip empty-fence code blocks whose content starts with "tool_calls" (inline JSON format)
    .replace(/```[ \t]*\ntool_calls[\s\S]*?```/gi, "")
    // Strip tool_calls XML format (LLM sometimes uses this instead of backtick fences)
    .replace(/<tool_calls>[\s\S]*?<\/tool_calls>/gi, "")
    // Defensive: strip a leaked, unfenced tool-call args fragment (malformed JSON that
    // escaped backend cleaning). Anchored on keys that never appear in real prose, so
    // this only removes machine residue — e.g. ..."assigned_agent_id":"…","agent_overrides":{…}}}]
    .replace(/[^\n]*?"(?:assigned_agent_id|agent_overrides|system_prompt_append|tool_name)"\s*:[\s\S]*?\}{1,3}\s*\]?/gi, "")
    // Strip echoed tool-result header lines: **toolname**: (model re-echoing injection format)
    .replace(/^\*\*[\w_]+\*\*:[ \t]*$/gm, "")
    // Remove orphaned backtick-only lines left after fence stripping
    .replace(/^```\s*$/gm, "")
    .trim();
  // Live: an as-yet-unclosed <think>/<thinking> (closing tag not streamed yet).
  // THINKING_RE only matches closed blocks, so while streaming we surface the
  // open block's current text as a live reasoning block and keep it out of the
  // answer body — "watch it think", matching NexoraCLI. A finished message always
  // has the closing tag, handled above.
  if (isStreaming) {
    const oThink = strippedContent.lastIndexOf("<think>");
    const oThinking = strippedContent.lastIndexOf("<thinking>");
    const idx = Math.max(oThink, oThinking);
    if (idx !== -1) {
      const tag = oThinking > oThink ? "<thinking>" : "<think>";
      const live = strippedContent.slice(idx + tag.length).trim();
      if (live) thinkingBlocks.push(live);
      strippedContent = strippedContent.slice(0, idx).trim();
    }
  }
  // Nuke any orphan/unpaired reasoning tag that escaped the steps above — a model
  // sometimes emits a bare </think> (or <think>) with no match. Must never render.
  strippedContent = strippedContent.replace(/<\/?(?:think|thinking)\s*>/gi, "").trim();
  // A whole-message bare tool-call/decompose JSON the model emitted instead of using
  // the protocol — [{"name":"task_create","args":{…}}] or [{"title":…,"task":…}] or a
  // single {"name":…,"args":…} object. Not user-facing; drop it.
  if (
    /^\s*\[\s*\{[\s\S]*?("name"\s*:\s*"[\w_]+"\s*,\s*"args"|"task"|"tool_name"|"skills")[\s\S]*\}\s*\]\s*$/.test(strippedContent) ||
    /^\s*\{\s*"name"\s*:\s*"[\w_]+"\s*,\s*"args"\s*:[\s\S]*\}\s*$/.test(strippedContent)
  ) {
    strippedContent = "";
  }
  const isMyMessage = isUser && isCurrentUser;
  const isOtherUserMessage = isUser && !isCurrentUser && !isAgent;
  // Tool-result detection driven by structured metadata, not content sniffing.
  const isToolResult = metadata?.kind === "tool_result_injection";

  const displayName = isMyMessage ? (userName || "You") : (agentName || userName || "Assistant");
  const usage = metadata?.usage;
  const hasMetadata = !isMyMessage && metadata && (
    usage || metadata.cost_usd != null || metadata.duration_ms != null ||
    metadata.session_id || metadata.thread_id || metadata.model
  );

  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(content);

  const handleCopy = () => {
    copyToClipboard(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleEditSend = () => {
    const trimmed = editContent.trim();
    if (trimmed && messageId && onEditSubmit) {
      onEditSubmit(messageId, trimmed);
    }
    setIsEditing(false);
  };

  const handleEditCancel = () => {
    setIsEditing(false);
    setEditContent(content);
  };

  if (!isStreaming && !strippedContent && thinkingBlocks.length === 0) {
    return null;
  }

  return (
    <div className={cn(
      "group flex gap-3 px-4 animate-fade-in",
      isContinuation ? "pt-1 pb-0" : "pt-4 pb-0",
      isMyMessage && "flex-row-reverse",
      excluded && "opacity-40"
    )}>
      {/* Avatar */}
      {isContinuation ? (
        <div className="w-8 shrink-0" />
      ) : (
        <div
          className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-sm",
            isMyMessage
              ? "bg-primary text-primary-foreground"
              : "bg-accent text-accent-foreground border border-border"
          )}
        >
          {isUser
            ? (avatarEmoji ? avatarEmoji : <User className="w-4 h-4" />)
            : <Bot className="w-4 h-4" />}
        </div>
      )}

      {/* Content */}
      <div className={cn("flex-1 min-w-0 space-y-1", isMyMessage && "items-end flex flex-col")}>
        {/* Name row — hidden for continuation messages */}
        {!isContinuation && (
        <div className={cn("flex items-center gap-2 text-xs text-muted-foreground", isMyMessage && "flex-row-reverse")}>
          <span className="font-medium">{displayName}</span>
          {isAgent && (
            <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded font-medium">Agent</span>
          )}
          {isOtherUserMessage && (
            <span className="text-[10px] bg-accent/10 text-accent-foreground px-1.5 py-0.5 rounded font-medium">Partner</span>
          )}
          {isToolResult && (
            <span className="text-[10px] bg-green-400/10 text-green-400 px-1.5 py-0.5 rounded font-medium">Tool Result</span>
          )}
          {providerUsed && (
            <span className="text-[10px] bg-accent px-1.5 py-0.5 rounded">{providerUsed}</span>
          )}
          {createdAt && (
            <span
              className={cn("text-[10px] text-muted-foreground", !isMyMessage && "ml-auto")}
              title={new Date(createdAt).toLocaleString()}
            >
              {formatMessageTime(createdAt)}
            </span>
          )}
        </div>
        )}

        {/* Reasoning panel — OUTSIDE the answer bubble (like the "Agent · N actions"
            card), so thinking reads as its own collapsible block, not bubble text. */}
        {!isMyMessage && thinkingBlocks.length > 0 && (
          <ThinkingBlock blocks={thinkingBlocks} live={!!isStreaming && !strippedContent} />
        )}

        {/* Bubble or edit textarea */}
        {isMyMessage && isEditing ? (
          <div className="max-w-[85%] w-full space-y-2">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") handleEditCancel();
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleEditSend();
              }}
              className="w-full rounded-xl border border-primary/40 bg-primary/5 text-sm px-4 py-3 resize-none focus:outline-none focus:ring-1 focus:ring-primary/40 text-foreground"
              rows={Math.max(2, editContent.split("\n").length + 1)}
              autoFocus
            />
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={handleEditCancel}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                <X className="w-3 h-3" /> Cancel
              </button>
              <button
                onClick={handleEditSend}
                disabled={!editContent.trim()}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-40"
              >
                <SendHorizonal className="w-3 h-3" /> Send
              </button>
            </div>
          </div>
        ) : (!strippedContent && !isToolResult) ? null : (
          <div
            className={cn(
              "max-w-[85%] rounded-xl px-4 py-3 text-sm",
              isMyMessage
                ? "bg-primary text-primary-foreground rounded-tr-sm"
                : "bg-card border border-border rounded-tl-sm prose-chat"
            )}
          >
            {isToolResult ? (
              <ToolResultDisplay content={strippedContent} />
            ) : isUser && !isAgent ? (
              <p className="whitespace-pre-wrap">{strippedContent}</p>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node, className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || "");
                    const lang = match?.[1];
                    const isBlock = className?.startsWith("language-");
                    if (isBlock && lang === "tool_calls") return null;
                    if (isBlock) {
                      return <CodeBlock code={String(children).replace(/\n$/, "")} language={lang} />;
                    }
                    return <code className="px-1 py-0.5 rounded text-xs font-mono bg-accent text-accent-foreground" {...props}>{children}</code>;
                  },
                }}
              >
                {isStreaming ? completeStreamingMarkdown(strippedContent) : strippedContent}
              </ReactMarkdown>
            )}
            {isStreaming && <span className="streaming-cursor" />}
          </div>
        )}

        {/* Action buttons */}
        {!isStreaming && !isEditing && !isToolResult && (
          <div className={cn(
            "flex items-center gap-0.5 transition-opacity",
            excluded ? "opacity-60" : "opacity-0 group-hover:opacity-100",
            isMyMessage ? "self-end" : "self-start"
          )}>
            {messageId && onExcludedToggle && (
              <button
                onClick={() => onExcludedToggle(messageId, !excluded)}
                title={excluded ? "Include in AI context" : "Exclude from AI context"}
                className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              >
                {excluded
                  ? <EyeOff className="w-3 h-3 text-muted-foreground/60" />
                  : <Eye className="w-3 h-3" />}
              </button>
            )}
            <button
              onClick={handleCopy}
              title="Copy message"
              className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            >
              {copied
                ? <Check className="w-3 h-3 text-green-400" />
                : <Copy className="w-3 h-3" />}
            </button>
            {isMyMessage && messageId && onEditSubmit && (
              <button
                onClick={() => setIsEditing(true)}
                title="Edit message"
                className="p-1 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              >
                <Pencil className="w-3 h-3" />
              </button>
            )}
            {hasMetadata && (
              <div className="flex items-center gap-2 flex-wrap ml-1.5 border-l border-border/50 pl-1.5">
                {metadata.model && (
                  <span className="text-[10px] font-mono text-muted-foreground">{metadata.model}</span>
                )}
                {usage && (usage.input_tokens != null || usage.output_tokens != null) && (
                  <span className="text-[10px] text-muted-foreground">
                    {usage.input_tokens ?? 0}↑&nbsp;{usage.output_tokens ?? 0}↓
                    {usage.cached_input_tokens ? <> · {usage.cached_input_tokens} cached</> : null}
                  </span>
                )}
                {metadata.cost_usd != null && (
                  <span className="text-[10px] text-muted-foreground">${metadata.cost_usd.toFixed(5)}</span>
                )}
                {metadata.duration_ms != null && (
                  <span className="text-[10px] text-muted-foreground">{(metadata.duration_ms / 1000).toFixed(1)}s</span>
                )}
                {metadata.session_id && (
                  <span className="text-[10px] font-mono text-muted-foreground" title={metadata.session_id}>
                    sid·{metadata.session_id.slice(-8)}
                  </span>
                )}
                {metadata.thread_id && (
                  <span className="text-[10px] font-mono text-muted-foreground" title={metadata.thread_id}>
                    tid·{metadata.thread_id.slice(-8)}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
