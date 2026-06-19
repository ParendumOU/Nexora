"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  SendHorizonal, Square, Zap, Brain, Telescope,
  ChevronDown, Check, Bot, Cpu, Paperclip, FolderKanban, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { agentsApi, providersApi, projectsApi } from "@/lib/api";
import * as Popover from "@radix-ui/react-popover";
import { ProjectPicker } from "@/components/ui/project-picker";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface FlowSendOptions {
  agent_id: string | null;
  provider_chain_id: string | null;
  mode: "flash" | "think" | "deep";
  project_ids: string[];
}

interface MentionState {
  atIndex: number;   // position of @ char
  endIndex: number;  // current cursor
  query: string;     // text typed after @
}

// ── Mode config ───────────────────────────────────────────────────────────────

const MODES = [
  { key: "flash" as const, label: "Flash",     Icon: Zap,       iconClass: "text-yellow-400", desc: "Fast, no extra reasoning" },
  { key: "think" as const, label: "Think",     Icon: Brain,     iconClass: "text-blue-400",   desc: "Step-by-step reasoning"   },
  { key: "deep"  as const, label: "Deep",      Icon: Telescope, iconClass: "text-violet-400", desc: "Thorough, considers edge cases" },
];

// ── Shared pill ───────────────────────────────────────────────────────────────

function Pill({ children, active, className }: {
  children: React.ReactNode;
  active?: boolean;
  className?: string;
}) {
  return (
    <span className={cn(
      "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-colors shrink-0 cursor-pointer select-none",
      active
        ? "border-primary/60 bg-primary/10 text-primary"
        : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-accent/40",
      className,
    )}>
      {children}
    </span>
  );
}

// ── Mode selector ─────────────────────────────────────────────────────────────

function ModeSelector({ value, onChange }: { value: "flash" | "think" | "deep"; onChange: (v: "flash" | "think" | "deep") => void }) {
  const current = MODES.find((m) => m.key === value)!;
  const Icon = current.Icon;
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="outline-none">
          <Pill active={value !== "flash"}>
            <Icon className={cn("w-3 h-3", current.iconClass)} />
            {current.label}
            <ChevronDown className="w-3 h-3 opacity-60" />
          </Pill>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6} className="z-50 w-56 bg-card border border-border rounded-xl shadow-xl p-1">
          {MODES.map((m) => {
            const MIcon = m.Icon;
            return (
              <Popover.Close asChild key={m.key}>
                <button type="button" onClick={() => onChange(m.key)}
                  className="flex items-start gap-3 w-full px-3 py-2.5 rounded-lg text-left hover:bg-accent/50 transition-colors"
                >
                  <MIcon className={cn("w-4 h-4 mt-0.5 shrink-0", m.iconClass)} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{m.label}</span>
                      {value === m.key && <Check className="w-3.5 h-3.5 text-primary" />}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{m.desc}</p>
                  </div>
                </button>
              </Popover.Close>
            );
          })}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ── Agent selector pill (toolbar, sets default agent) ─────────────────────────

function AgentSelectorPill({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const [search, setSearch] = useState("");
  const { data: agents = [] } = useQuery<Array<{ id: string; name: string; agent_type: string }>>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });
  const selected = agents.find((a) => a.id === value);
  const filtered = agents.filter((a) => a.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <Popover.Root onOpenChange={(o) => { if (!o) setSearch(""); }}>
      <Popover.Trigger asChild>
        <button type="button" className="outline-none">
          <Pill active={!!value}>
            <Bot className="w-3 h-3" />
            {selected ? selected.name : "Agent"}
            <ChevronDown className="w-3 h-3 opacity-60" />
          </Pill>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6} className="z-50 w-60 bg-card border border-border rounded-xl shadow-xl p-1">
          <div className="px-2 pt-1 pb-1.5">
            <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search agents…"
              className="w-full text-xs bg-transparent border-b border-border pb-1.5 outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            <Popover.Close asChild>
              <button type="button" onClick={() => onChange(null)}
                className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-left hover:bg-accent/50 transition-colors text-sm"
              >
                <span className="text-muted-foreground">No agent (default)</span>
                {!value && <Check className="w-3.5 h-3.5 text-primary" />}
              </button>
            </Popover.Close>
            {filtered.map((a) => (
              <Popover.Close asChild key={a.id}>
                <button type="button" onClick={() => onChange(a.id)}
                  className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-left hover:bg-accent/50 transition-colors"
                >
                  <div>
                    <p className="text-sm font-medium">{a.name}</p>
                    <p className="text-xs text-muted-foreground capitalize">{a.agent_type.replace(/_/g, " ")}</p>
                  </div>
                  {value === a.id && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                </button>
              </Popover.Close>
            ))}
            {filtered.length === 0 && <p className="text-xs text-muted-foreground px-3 py-2">No agents found</p>}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ── Chain selector pill ────────────────────────────────────────────────────────

function ChainSelectorPill({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const { data: allChains = [] } = useQuery<Array<{ id: string; name: string; is_default: boolean }>>({
    queryKey: ["provider-chains"],
    queryFn: () => providersApi.chains().then((r) => r.data),
  });
  const chains = allChains.filter((c) => !c.name.startsWith("__solo__"));
  const selected = chains.find((c) => c.id === value);
  const label = selected?.name ?? (chains.find((c) => c.is_default)?.name ?? "Model");
  if (chains.length === 0) return null;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="outline-none">
          <Pill active={!!value}>
            <Cpu className="w-3 h-3" />
            {label}
            <ChevronDown className="w-3 h-3 opacity-60" />
          </Pill>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6} className="z-50 w-56 bg-card border border-border rounded-xl shadow-xl p-1">
          <Popover.Close asChild>
            <button type="button" onClick={() => onChange(null)}
              className="flex items-center justify-between w-full px-3 py-2.5 rounded-lg text-left hover:bg-accent/50 transition-colors"
            >
              <div>
                <p className="text-sm font-medium">Chat default</p>
                <p className="text-xs text-muted-foreground">Use chain assigned to this session</p>
              </div>
              {!value && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
            </button>
          </Popover.Close>
          {chains.map((c) => (
            <Popover.Close asChild key={c.id}>
              <button type="button" onClick={() => onChange(c.id)}
                className="flex items-center justify-between w-full px-3 py-2.5 rounded-lg text-left hover:bg-accent/50 transition-colors"
              >
                <div>
                  <p className="text-sm font-medium">{c.name}</p>
                  {c.is_default && <p className="text-xs text-muted-foreground">Default chain</p>}
                </div>
                {value === c.id && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
              </button>
            </Popover.Close>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ── Project selector pill ─────────────────────────────────────────────────────

function ProjectSelectorPill({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const { data: projects = [] } = useQuery<Array<{ id: string; name: string; repo_url?: string | null }>>({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list().then((r) => r.data),
  });
  if (projects.length === 0) return null;

  const label = value.length === 0
    ? "Project"
    : value.length === 1
      ? (projects.find((p) => p.id === value[0])?.name ?? "1 project")
      : `${value.length} projects`;

  return (
    <ProjectPicker multiple projects={projects} value={value} onChange={onChange}>
      <button type="button" className="outline-none">
        <Pill active={value.length > 0}>
          <FolderKanban className="w-3 h-3" />
          {label}
          <ChevronDown className="w-3 h-3 opacity-60" />
        </Pill>
      </button>
    </ProjectPicker>
  );
}

// ── Main FlowInput ────────────────────────────────────────────────────────────

export function FlowInput({
  onSend,
  onStop,
  isStreaming,
  disabled,
  initialAgentId,
  initialProjectId,
  initialChainId,
}: {
  onSend: (content: string, options: FlowSendOptions) => void;
  onStop?: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  initialAgentId?: string | null;
  initialProjectId?: string | null;
  initialChainId?: string | null;
}) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"flash" | "think" | "deep">("flash");
  const [agentId, setAgentId] = useState<string | null>(initialAgentId ?? null);
  const [chainId, setChainId] = useState<string | null>(initialChainId ?? null);
  const [projectIds, setProjectIds] = useState<string[]>(initialProjectId ? [initialProjectId] : []);
  const [mention, setMention] = useState<MentionState | null>(null);
  const [showFileInput, setShowFileInput] = useState(false);
  const [filePath, setFilePath] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Fetch agents for @mention
  const { data: agents = [] } = useQuery<Array<{ id: string; name: string; agent_type: string }>>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });

  const filteredMentionAgents = mention
    ? agents.filter((a) => a.name.toLowerCase().includes(mention.query.toLowerCase())).slice(0, 8)
    : [];

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, []);

  // Detect if cursor is inside a @word mention
  const detectMention = useCallback((text: string, cursor: number) => {
    const before = text.slice(0, cursor);
    const atIdx = before.lastIndexOf("@");
    if (atIdx === -1) { setMention(null); return; }
    const afterAt = before.slice(atIdx + 1);
    // Cancel if there's a space after @ (mention is complete/abandoned)
    if (afterAt.includes(" ") || afterAt.includes("\n")) { setMention(null); return; }
    // @ must be at start or preceded by whitespace
    if (atIdx > 0 && !/[\s,]/.test(text[atIdx - 1])) { setMention(null); return; }
    setMention({ atIndex: atIdx, endIndex: cursor, query: afterAt });
  }, []);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    const cursor = e.target.selectionStart ?? newValue.length;
    setValue(newValue);
    adjustHeight();
    detectMention(newValue, cursor);
  }, [adjustHeight, detectMention]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Escape") { setMention(null); return; }
    if (e.key === "Enter" && !e.shiftKey && !mention) {
      e.preventDefault();
      handleSend();
    }
  }, [mention]); // eslint-disable-line react-hooks/exhaustive-deps

  // Insert @AgentName when user picks from dropdown
  const insertMention = useCallback((agentName: string) => {
    if (!mention) return;
    const before = value.slice(0, mention.atIndex);
    const after = value.slice(mention.endIndex);
    const newValue = `${before}@${agentName} ${after}`;
    setValue(newValue);
    setMention(null);
    setTimeout(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      const pos = mention.atIndex + agentName.length + 2;
      ta.focus();
      ta.setSelectionRange(pos, pos);
    }, 0);
  }, [value, mention]);

  // Insert [file:path] reference
  const insertFilePath = useCallback(() => {
    const trimmed = filePath.trim();
    if (!trimmed) return;
    const ref = `[file:${trimmed}]`;
    setValue((v) => (v ? `${v} ${ref} ` : `${ref} `));
    setFilePath("");
    setShowFileInput(false);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }, [filePath]);

  const handleSend = useCallback(() => {
    const content = value.trim();
    if (!content || isStreaming || disabled) return;
    onSend(content, { agent_id: agentId, provider_chain_id: chainId, mode, project_ids: projectIds });
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [value, isStreaming, disabled, onSend, agentId, chainId, mode, projectIds]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const hasOverrides = agentId || chainId || projectIds.length > 0 || mode !== "flash";

  return (
    <div className="border-t border-border bg-background px-4 py-3 shrink-0">
      <div className="max-w-4xl mx-auto">

        {/* @mention dropdown — floats above input */}
        {mention && filteredMentionAgents.length > 0 && (
          <div className="mb-2 bg-card border border-border rounded-xl shadow-xl overflow-hidden">
            <div className="px-3 py-1.5 border-b border-border">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                Mention agent
              </span>
            </div>
            <div className="max-h-44 overflow-y-auto p-1">
              {filteredMentionAgents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); insertMention(agent.name); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 rounded-lg hover:bg-accent/60 transition-colors text-left"
                >
                  <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <Bot className="w-3 h-3 text-primary" />
                  </div>
                  <div>
                    <p className="text-xs font-medium">{agent.name}</p>
                    <p className="text-[10px] text-muted-foreground capitalize">
                      {agent.agent_type.replace(/_/g, " ")}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* File path input */}
        {showFileInput && (
          <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-card border border-border rounded-xl">
            <Paperclip className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <input
              autoFocus
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") insertFilePath();
                if (e.key === "Escape") { setShowFileInput(false); setFilePath(""); }
              }}
              placeholder="File path — e.g. /src/components/App.tsx"
              className="flex-1 text-xs bg-transparent outline-none placeholder:text-muted-foreground font-mono"
            />
            <button
              onClick={insertFilePath}
              className="text-[10px] text-primary font-medium hover:text-primary/80 transition-colors"
            >
              Attach
            </button>
            <button
              onClick={() => { setShowFileInput(false); setFilePath(""); }}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        )}

        {/* Main input card */}
        <div className="bg-card border border-border rounded-xl focus-within:border-primary/40 transition-colors">

          {/* Textarea */}
          <div className="px-4 pt-3 pb-2">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              onSelect={(e) => detectMention(value, (e.target as HTMLTextAreaElement).selectionStart ?? value.length)}
              placeholder="Intervene in the session… type @ to mention an agent"
              rows={1}
              disabled={disabled}
              className="w-full bg-transparent text-sm resize-none outline-none placeholder:text-muted-foreground min-h-[24px] max-h-[200px] leading-relaxed"
            />
          </div>

          {/* Toolbar */}
          <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              <ModeSelector value={mode} onChange={setMode} />
              <AgentSelectorPill value={agentId} onChange={setAgentId} />
              <ChainSelectorPill value={chainId} onChange={setChainId} />
              <ProjectSelectorPill value={projectIds} onChange={setProjectIds} />

              {/* File attach button */}
              <button
                type="button"
                onClick={() => setShowFileInput((v) => !v)}
                title="Attach file path reference"
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-colors shrink-0 cursor-pointer select-none",
                  showFileInput
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-accent/40"
                )}
              >
                <Paperclip className="w-3 h-3" />
              </button>

              {hasOverrides && (
                <button
                  type="button"
                  onClick={() => { setAgentId(null); setChainId(null); setProjectIds([]); setMode("flash"); }}
                  className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors px-1"
                  title="Reset all options"
                >
                  <X className="w-3 h-3" /> Reset
                </button>
              )}
            </div>

            <div className="shrink-0">
              {isStreaming ? (
                <Button
                  variant="ghost" size="icon" onClick={onStop}
                  className="h-7 w-7 hover:bg-destructive/10 hover:text-destructive"
                >
                  <Square className="w-3.5 h-3.5" />
                </Button>
              ) : (
                <Button
                  size="icon" onClick={handleSend}
                  disabled={!value.trim() || disabled}
                  className="h-7 w-7"
                >
                  <SendHorizonal className="w-3.5 h-3.5" />
                </Button>
              )}
            </div>
          </div>
        </div>

        <p className="text-center text-[10px] text-muted-foreground mt-1.5">
          Use <span className="font-mono bg-accent px-1 rounded">@AgentName</span> to mention an agent ·{" "}
          <span className="font-mono bg-accent px-1 rounded">📎</span> to attach a file path
        </p>
      </div>
    </div>
  );
}
