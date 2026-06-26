"use client";
import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  SendHorizonal, Square, Zap, Brain, Telescope,
  ChevronDown, Check, Bot, X, Cpu, Settings,
  Paperclip, Mic, MicOff, FileText, Image, File, Code2, Archive,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { agentsApi, providersApi, chatFilesApi } from "@/lib/api";
import { ProviderSelector } from "@/components/chat/provider-selector";
import { ChatFile } from "@/components/chat/chat-files-panel";
import * as Popover from "@radix-ui/react-popover";

// ─── Types ────────────────────────────────────────────────────────

export interface SendOptions {
  agent_id: string | null;
  provider_chain_id: string | null;
  mode: "flash" | "think" | "deep";
  model_name?: string | null;
  enable_agent: boolean;
  file_ids?: string[];
  yolo?: boolean;
  autopilot?: boolean;
}

interface ChainStep { position: number; model_name: string | null; provider_type: string; account_count: number }
interface Chain { id: string; name: string; is_default: boolean; steps: ChainStep[] }
interface FlatProvider { id: string; name: string; provider_type: string; is_active: boolean; available_models: string[] }

export interface ChatInputProps {
  onSend: (content: string, options: SendOptions) => void;
  onStop?: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  chatId: string;
  currentChainId?: string | null;
  currentDirectProviderId?: string | null;
  defaultAgentId?: string | null;
  onFilesUploaded?: (files: ChatFile[]) => void;
  availableFiles?: ChatFile[];
}

// ─── Mode config ──────────────────────────────────────────────────

const MODES = [
  { key: "flash" as const, label: "Flash", Icon: Zap, iconClass: "text-yellow-400", description: "Fast response, no extra reasoning" },
  { key: "think" as const, label: "Think", Icon: Brain, iconClass: "text-blue-400", description: "Step-by-step reasoning before answering" },
  { key: "deep" as const, label: "Deep", Icon: Telescope, iconClass: "text-violet-400", description: "Thorough analysis, considers edge cases" },
];

// ─── Pill button ──────────────────────────────────────────────────

function Pill({ children, active, className }: { children: React.ReactNode; active?: boolean; className?: string }) {
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

// ─── Mode selector ────────────────────────────────────────────────

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
                <button
                  type="button"
                  onClick={() => onChange(m.key)}
                  className="flex items-start gap-3 w-full px-3 py-2.5 rounded-lg text-left hover:bg-accent/50 transition-colors"
                >
                  <MIcon className={cn("w-4 h-4 mt-0.5 shrink-0", m.iconClass)} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{m.label}</span>
                      {value === m.key && <Check className="w-3.5 h-3.5 text-primary" />}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{m.description}</p>
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

// ─── Agent selector ───────────────────────────────────────────────

interface AgentItem { id: string; name: string; agent_type: string }

function AgentSelector({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const [search, setSearch] = useState("");
  const { data: agents = [] } = useQuery<AgentItem[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then((r) => r.data),
  });
  const selected = agents.find((a) => a.id === value);
  const filtered = agents.filter((a) => a.name.toLowerCase().includes(search.toLowerCase()));
  const displayName = selected?.name ?? (agents.length > 0 ? agents[0].name : "Agent");
  return (
    <Popover.Root onOpenChange={(o) => { if (!o) setSearch(""); }}>
      <Popover.Trigger asChild>
        <button type="button" className="outline-none">
          <Pill active={!!value}><Bot className="w-3 h-3" />{displayName}<ChevronDown className="w-3 h-3 opacity-60" /></Pill>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6} className="z-50 w-60 bg-card border border-border rounded-xl shadow-xl p-1">
          <div className="px-2 pt-1 pb-1.5">
            <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search agents…"
              className="w-full text-xs bg-transparent border-b border-border pb-1.5 outline-none placeholder:text-muted-foreground" />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {filtered.map((agent) => (
              <Popover.Close asChild key={agent.id}>
                <button type="button" onClick={() => onChange(agent.id)}
                  className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-left hover:bg-accent/50 transition-colors">
                  <div>
                    <p className="text-sm font-medium">{agent.name}</p>
                    <p className="text-xs text-muted-foreground capitalize">{agent.agent_type.replace(/_/g, " ")}</p>
                  </div>
                  {value === agent.id && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
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

// ─── Model selector ───────────────────────────────────────────────

function ModelSelector({ value, onChange, currentChainId, currentDirectProviderId }: {
  value: string | null; onChange: (v: string | null) => void;
  currentChainId?: string | null; currentDirectProviderId?: string | null;
}) {
  const [customInput, setCustomInput] = useState("");
  const [showCustom, setShowCustom] = useState(false);
  const { data: chains = [] } = useQuery<Chain[]>({ queryKey: ["chains"], queryFn: () => providersApi.chains().then((r) => r.data) });
  const { data: allProviders = [] } = useQuery<FlatProvider[]>({ queryKey: ["providers"], queryFn: () => providersApi.list().then((r) => r.data) });
  const currentChain = chains.find((c) => c.id === currentChainId);
  const firstStepType = currentChain?.steps?.[0]?.provider_type;
  const activeProvider = (firstStepType ? allProviders.find((p) => p.provider_type === firstStepType) : null)
    ?? allProviders.find((p) => p.id === currentDirectProviderId)
    ?? allProviders.find((p) => p.is_active);
  const models = activeProvider?.available_models ?? [];
  useEffect(() => {
    if (value && models.length > 0 && !models.includes(value)) onChange(null);
  }, [models, value, onChange]);
  const handleClose = (open: boolean) => { if (!open) { setShowCustom(false); setCustomInput(""); } };
  return (
    <Popover.Root onOpenChange={handleClose}>
      <Popover.Trigger asChild>
        <button type="button" className="outline-none">
          <Pill active={!!value}><Cpu className="w-3 h-3" />{value ?? "Default model"}<ChevronDown className="w-3 h-3 opacity-60" /></Pill>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6} className="z-50 w-64 bg-card border border-border rounded-xl shadow-xl p-1">
          <Popover.Close asChild>
            <button type="button" onClick={() => onChange(null)}
              className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-left hover:bg-accent/50 transition-colors text-sm">
              <span className="text-muted-foreground">Provider default</span>
              {!value && <Check className="w-3.5 h-3.5 text-primary" />}
            </button>
          </Popover.Close>
          {models.length > 0 && (
            <div className="max-h-48 overflow-y-auto">
              {models.map((m) => (
                <Popover.Close asChild key={m}>
                  <button type="button" onClick={() => onChange(m)}
                    className="flex items-center justify-between w-full px-3 py-1.5 rounded-lg text-left hover:bg-accent/50 transition-colors">
                    <span className="text-xs font-mono truncate">{m}</span>
                    {value === m && <Check className="w-3.5 h-3.5 text-primary shrink-0 ml-2" />}
                  </button>
                </Popover.Close>
              ))}
            </div>
          )}
          {showCustom ? (
            <form onSubmit={(e) => { e.preventDefault(); if (customInput.trim()) onChange(customInput.trim()); setShowCustom(false); setCustomInput(""); }}
              className="flex gap-1 px-2 pb-1 pt-0.5">
              <input autoFocus value={customInput} onChange={(e) => setCustomInput(e.target.value)} placeholder="model-name"
                className="flex-1 text-xs bg-transparent border-b border-border outline-none placeholder:text-muted-foreground py-1" />
              <button type="submit" className="text-xs text-primary font-medium px-1 py-1 hover:opacity-80">Set</button>
            </form>
          ) : (
            <button type="button" onClick={() => setShowCustom(true)}
              className="flex w-full px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground rounded-lg hover:bg-accent/50 transition-colors">
              Custom…
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ─── File icon helper ─────────────────────────────────────────────

function FileChipIcon({ name, contentType }: { name: string; contentType: string }) {
  if (contentType.startsWith("image/")) return <Image className="w-3 h-3" />;
  if (/\.(zip|tar|gz|rar|7z)$/i.test(name)) return <Archive className="w-3 h-3" />;
  if (/\.(js|ts|tsx|jsx|py|go|rs|java|c|cpp|h|sh|json|yaml|yml|toml|sql|html|css)$/i.test(name)) return <Code2 className="w-3 h-3" />;
  if (contentType.startsWith("text/") || /\.(md|txt|log|csv)$/i.test(name)) return <FileText className="w-3 h-3" />;
  return <File className="w-3 h-3" />;
}

// ─── Main input ───────────────────────────────────────────────────

export function ChatInput({
  onSend, onStop, isStreaming, disabled, chatId,
  currentChainId, currentDirectProviderId, defaultAgentId,
  onFilesUploaded, availableFiles = [],
}: ChatInputProps) {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"flash" | "think" | "deep">("flash");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const [enableAgent, setEnableAgent] = useState(true);
  const [yolo, setYolo] = useState(false);
  const [autopilot, setAutopilot] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<ChatFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);

  // @mention autocomplete state
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStartPos, setMentionStartPos] = useState(0);
  const [mentionIndex, setMentionIndex] = useState(0);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const didSetDefaultAgent = useRef(false);

  const handleModelChange = useCallback((v: string | null) => {
    setModelOverride(v);
    if (v) localStorage.setItem(`chat:model:${chatId}`, v);
    else localStorage.removeItem(`chat:model:${chatId}`);
  }, [chatId]);

  const handleReset = useCallback(() => {
    setAgentId(null); setMode("flash"); setModelOverride(null); setEnableAgent(true);
    localStorage.removeItem(`chat:model:${chatId}`);
  }, [chatId]);

  const settingsHasNonDefault = !!(agentId || mode !== "flash" || modelOverride);

  useEffect(() => {
    const saved = localStorage.getItem(`chat:model:${chatId}`);
    if (saved) setModelOverride(saved);
  }, [chatId]);

  useEffect(() => {
    if (defaultAgentId && !didSetDefaultAgent.current) {
      setAgentId(defaultAgentId);
      didSetDefaultAgent.current = true;
    }
  }, [defaultAgentId]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta && document.activeElement !== ta) ta.focus();
  }, []);

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, []);

  // ─── File upload ───────────────────────────────────────────────

  const uploadFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setIsUploading(true);
    try {
      const res = await chatFilesApi.upload(chatId, files);
      const uploaded: ChatFile[] = res.data;
      setPendingFiles((prev) => {
        const ids = new Set(prev.map((f) => f.id));
        return [...prev, ...uploaded.filter((f) => !ids.has(f.id))];
      });
      onFilesUploaded?.(uploaded);
      qc.invalidateQueries({ queryKey: ["chat-files", chatId] });
    } catch (e) {
      console.error("Upload failed", e);
    } finally {
      setIsUploading(false);
    }
  }, [chatId, onFilesUploaded, qc]);

  // ─── Drag & drop ───────────────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) await uploadFiles(files);
  }, [uploadFiles]);

  // ─── Voice dictation ───────────────────────────────────────────

  const speechSupported = useMemo(() => {
    if (typeof window === "undefined") return false;
    const w = window as unknown as Record<string, unknown>;
    return !!(w.SpeechRecognition || w.webkitSpeechRecognition);
  }, []);

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }
    const w = window as unknown as Record<string, unknown>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR: new () => any = (w.SpeechRecognition || w.webkitSpeechRecognition) as new () => any;
    if (!SR) return;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";

    let baseText = value;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (ev: any) => {
      let interim = "";
      let finalSegment = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalSegment += t;
        else interim += t;
      }
      if (finalSegment) baseText += finalSegment;
      setValue(baseText + interim);
      setTimeout(adjustHeight, 0);
    };
    rec.onend = () => setIsRecording(false);
    rec.onerror = () => setIsRecording(false);

    recognitionRef.current = rec;
    rec.start();
    setIsRecording(true);
  }, [isRecording, value, adjustHeight]);

  useEffect(() => {
    return () => { recognitionRef.current?.stop(); };
  }, []);

  // ─── @mention autocomplete ────────────────────────────────────

  const mentionMatches = useMemo(() => {
    if (mentionQuery === null) return [];
    return availableFiles.filter((f) =>
      f.name.toLowerCase().includes(mentionQuery.toLowerCase())
    );
  }, [mentionQuery, availableFiles]);

  const insertMention = useCallback((file: ChatFile) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const before = value.slice(0, mentionStartPos);
    const after = value.slice(ta.selectionStart ?? value.length);
    const newVal = before + "@" + file.name + " " + after;
    setValue(newVal);
    setMentionQuery(null);
    setTimeout(() => {
      const pos = mentionStartPos + file.name.length + 2;
      ta.setSelectionRange(pos, pos);
      ta.focus();
      adjustHeight();
    }, 0);
  }, [value, mentionStartPos, adjustHeight]);

  // ─── Send ──────────────────────────────────────────────────────

  const handleSend = useCallback(() => {
    const content = value.trim();
    if (!content || isStreaming || disabled) return;
    recognitionRef.current?.stop();
    setIsRecording(false);
    onSend(content, {
      agent_id: agentId,
      provider_chain_id: null,
      mode,
      model_name: modelOverride,
      enable_agent: enableAgent,
      file_ids: pendingFiles.map((f) => f.id),
      yolo,
      autopilot,
    });
    setValue("");
    setPendingFiles([]);
    setMentionQuery(null);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [value, isStreaming, disabled, onSend, agentId, mode, modelOverride, enableAgent, yolo, autopilot, pendingFiles]);

  // ─── Textarea key handler ─────────────────────────────────────

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionQuery !== null && mentionMatches.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => Math.min(i + 1, mentionMatches.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Tab" || e.key === "Enter") {
        if (mentionMatches[mentionIndex]) {
          e.preventDefault();
          insertMention(mentionMatches[mentionIndex]);
          return;
        }
      }
      if (e.key === "Escape") {
        setMentionQuery(null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [mentionQuery, mentionMatches, mentionIndex, insertMention, handleSend]);

  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    setValue(text);
    adjustHeight();
    const cursorPos = e.target.selectionStart ?? text.length;
    const textBefore = text.slice(0, cursorPos);
    const atMatch = textBefore.match(/@([\w.\-]*)$/);
    if (atMatch) {
      setMentionQuery(atMatch[1]);
      setMentionStartPos(cursorPos - atMatch[0].length);
      setMentionIndex(0);
    } else {
      setMentionQuery(null);
    }
  }, [adjustHeight]);

  return (
    <div
      className="border-t border-border bg-background px-4 py-3"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="max-w-3xl mx-auto relative">
        {/* Drag overlay */}
        {isDragOver && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-primary/5 border-2 border-dashed border-primary/40 pointer-events-none">
            <p className="text-sm font-medium text-primary">Drop files to attach</p>
          </div>
        )}

        {/* @mention dropdown */}
        {mentionQuery !== null && mentionMatches.length > 0 && (
          <div className="absolute bottom-full mb-2 left-0 right-0 max-h-48 overflow-y-auto bg-card border border-border rounded-xl shadow-xl z-50">
            {mentionMatches.map((file, i) => (
              <button
                key={file.id}
                type="button"
                onMouseDown={(e) => { e.preventDefault(); insertMention(file); }}
                className={cn(
                  "flex items-center gap-2.5 w-full px-3 py-2 text-left hover:bg-accent/50 transition-colors",
                  i === mentionIndex && "bg-accent/50"
                )}
              >
                <FileChipIcon name={file.name} contentType={file.content_type} />
                <div className="flex-1 min-w-0">
                  <span className="text-xs font-medium truncate block">{file.name}</span>
                </div>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {file.size < 1024 * 1024
                    ? `${(file.size / 1024).toFixed(1)}KB`
                    : `${(file.size / 1024 / 1024).toFixed(1)}MB`}
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="bg-card border border-border rounded-xl focus-within:border-primary/40 transition-colors">
          {/* Pending files */}
          {pendingFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5">
              {pendingFiles.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-accent/60 border border-border text-xs max-w-[180px]"
                >
                  <FileChipIcon name={file.name} contentType={file.content_type} />
                  <span className="truncate flex-1 min-w-0">{file.name}</span>
                  <button
                    type="button"
                    onClick={() => setPendingFiles((prev) => prev.filter((f) => f.id !== file.id))}
                    className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Textarea */}
          <div className="px-4 pt-3 pb-2">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              placeholder={isRecording ? "Listening…" : "Message… (Enter to send, Shift+Enter for newline, @ to mention files)"}
              rows={1}
              className={cn(
                "w-full bg-transparent text-sm resize-none outline-none placeholder:text-muted-foreground min-h-[24px] max-h-[200px] leading-relaxed",
                isRecording && "placeholder:text-destructive/70"
              )}
            />
          </div>

          {/* Toolbar */}
          <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
            <div className="flex items-center gap-1.5">
              {/* Agent toggle */}
              <button
                type="button"
                onClick={() => setEnableAgent(!enableAgent)}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded-md border transition-colors shrink-0",
                  enableAgent
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80"
                )}
                title={enableAgent ? "Agent enabled" : "Agent disabled"}
              >
                <Bot className="w-3.5 h-3.5" />
              </button>

              {/* File attach */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className={cn(
                  "flex items-center justify-center w-6 h-6 rounded-md border transition-colors shrink-0",
                  pendingFiles.length > 0
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80",
                  isUploading && "opacity-50 cursor-not-allowed"
                )}
                title="Attach files"
              >
                <Paperclip className="w-3.5 h-3.5" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  if (files.length) uploadFiles(files);
                  e.target.value = "";
                }}
              />

              {/* Voice dictation */}
              {speechSupported && (
                <button
                  type="button"
                  onClick={toggleRecording}
                  className={cn(
                    "flex items-center justify-center w-6 h-6 rounded-md border transition-colors shrink-0",
                    isRecording
                      ? "border-destructive/60 bg-destructive/10 text-destructive animate-pulse"
                      : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80"
                  )}
                  title={isRecording ? "Stop recording" : "Voice input"}
                >
                  {isRecording ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
                </button>
              )}

              {/* Settings gear */}
              <Popover.Root>
                <Popover.Trigger asChild>
                  <button
                    type="button"
                    className={cn(
                      "relative flex items-center justify-center w-6 h-6 rounded-md border transition-colors shrink-0",
                      settingsHasNonDefault
                        ? "border-primary/60 bg-primary/10 text-primary"
                        : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80"
                    )}
                    title="Chat settings"
                  >
                    <Settings className="w-3.5 h-3.5" />
                    {settingsHasNonDefault && (
                      <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-primary" />
                    )}
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content side="top" align="start" sideOffset={8} className="z-50 w-64 bg-card border border-border rounded-xl shadow-xl p-3">
                    <div className={cn("space-y-2", !enableAgent && "opacity-40 pointer-events-none")}>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground w-14 shrink-0">Mode</span>
                        <ModeSelector value={mode} onChange={setMode} />
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground w-14 shrink-0">Agent</span>
                        <AgentSelector value={agentId} onChange={setAgentId} />
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground w-14 shrink-0">Provider</span>
                        <ProviderSelector chatId={chatId} currentChainId={currentChainId} currentDirectProviderId={currentDirectProviderId} side="top" asPill />
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground w-14 shrink-0">Model</span>
                        <ModelSelector value={modelOverride} onChange={handleModelChange} currentChainId={currentChainId} currentDirectProviderId={currentDirectProviderId} />
                      </div>
                    </div>
                    {/* YOLO: skip the human-in-the-loop approval prompt for this chat */}
                    <div className="mt-2 pt-2 border-t border-border flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <span className="text-xs font-medium">YOLO</span>
                        <p className="text-[10px] text-muted-foreground leading-tight">Auto-approve risky tools (no prompt)</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setYolo((v) => !v)}
                        className={cn(
                          "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                          yolo ? "bg-red-500" : "bg-muted"
                        )}
                        title={yolo ? "YOLO on — tools run without approval" : "YOLO off — risky tools need approval"}
                      >
                        <span className={cn(
                          "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
                          yolo ? "translate-x-4" : "translate-x-0.5"
                        )} />
                      </button>
                    </div>
                    {/* Autopilot: decompose the objective once and let the platform run
                        the whole roadmap (milestones → micro-tasks → specialists) by code */}
                    <div className="mt-2 pt-2 border-t border-border flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <span className="text-xs font-medium">Autopilot</span>
                        <p className="text-[10px] text-muted-foreground leading-tight">Plan once, then auto-build the whole roadmap with a team of agents</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setAutopilot((v) => !v)}
                        className={cn(
                          "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                          autopilot ? "bg-primary" : "bg-muted"
                        )}
                        title={autopilot ? "Autopilot on — your next message becomes a project the agents build autonomously" : "Autopilot off"}
                      >
                        <span className={cn(
                          "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
                          autopilot ? "translate-x-4" : "translate-x-0.5"
                        )} />
                      </button>
                    </div>
                    {(settingsHasNonDefault || !enableAgent) && (
                      <div className="mt-2.5 pt-2 border-t border-border">
                        <button type="button" onClick={handleReset}
                          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors">
                          <X className="w-3 h-3" /> Reset to defaults
                        </button>
                      </div>
                    )}
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>
            </div>

            <div className="flex items-center gap-2">
              {isStreaming ? (
                <Button variant="ghost" size="icon" onClick={onStop} className="h-7 w-7 hover:bg-destructive/10 hover:text-destructive">
                  <Square className="w-3.5 h-3.5" />
                </Button>
              ) : (
                <Button size="icon" onClick={handleSend} disabled={!value.trim() || disabled} className="h-7 w-7">
                  <SendHorizonal className="w-3.5 h-3.5" />
                </Button>
              )}
            </div>
          </div>
        </div>

        <p className="text-center text-[10px] text-muted-foreground mt-1.5">
          Nexora can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  );
}
