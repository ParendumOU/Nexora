"use client";

import { use, useState, useEffect, useRef } from "react";
import { Bot, Send, Loader2, AlertCircle, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentInfo {
  name: string;
  description: string | null;
  agent_type: string;
  soul: {
    personality?: string;
    communication_style?: string;
  };
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// ── API helpers (bare fetch, no auth) ────────────────────────────────────────

async function fetchPublicAgent(token: string): Promise<AgentInfo> {
  const res = await fetch(`/api/public/agents/${token}`);
  if (!res.ok) throw new Error("Agent not found or sharing is disabled");
  return res.json();
}

async function sendPublicMessage(token: string, message: string): Promise<string> {
  const res = await fetch(`/api/public/agents/${token}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (res.status === 429) throw new Error("Rate limit exceeded. Please wait a moment before sending another message.");
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || "Failed to get response");
  }
  const data = await res.json();
  return (data as { response: string }).response;
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg, agentName }: { msg: ChatMessage; agentName: string }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex gap-3 px-4 py-2", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
          <Bot className="w-3.5 h-3.5 text-primary" />
        </div>
      )}
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-sm"
            : "bg-muted text-foreground rounded-tl-sm"
        )}
      >
        <p className="whitespace-pre-wrap break-words">{msg.content}</p>
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-0.5">
          <span className="text-xs font-semibold text-primary">U</span>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PublicAgentChatPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetchPublicAgent(token)
      .then(setAgent)
      .catch((e: unknown) => setLoadError((e as Error).message));
  }, [token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const submit = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSendError(null);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    try {
      const reply = await sendPublicMessage(token, text);
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (e: unknown) {
      setSendError((e as Error).message);
    } finally {
      setSending(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  // ── Loading / error states ────────────────────────────────────────────────

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-6 text-center">
        <div className="w-14 h-14 rounded-2xl bg-destructive/10 flex items-center justify-center">
          <AlertCircle className="w-7 h-7 text-destructive" />
        </div>
        <div>
          <h1 className="text-lg font-semibold">Agent unavailable</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-xs">{loadError}</p>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // ── Chat UI ───────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-border shrink-0 bg-background/80 backdrop-blur-sm">
        <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <Bot className="w-4.5 h-4.5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-semibold truncate">{agent.name}</h1>
          {agent.description && (
            <p className="text-xs text-muted-foreground truncate">{agent.description}</p>
          )}
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/10 text-green-500 border border-green-500/20 font-medium shrink-0">
          Online
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-4 space-y-1">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-6 pb-10">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center">
              <MessageSquare className="w-8 h-8 text-primary/60" />
            </div>
            <div>
              <p className="text-base font-medium">Chat with {agent.name}</p>
              <p className="text-sm text-muted-foreground mt-1">
                {agent.soul?.personality
                  ? `Personality: ${agent.soul.personality}`
                  : "Send a message to get started"}
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} agentName={agent.name} />
          ))
        )}
        {sending && (
          <div className="flex gap-3 px-4 py-2 justify-start">
            <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
              <Bot className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="bg-muted rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Error banner */}
      {sendError && (
        <div className="mx-4 mb-2 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <p>{sendError}</p>
        </div>
      )}

      {/* Input */}
      <div className="px-4 py-3 border-t border-border shrink-0 bg-background">
        <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 focus-within:ring-1 focus-within:ring-ring">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={`Message ${agent.name}…`}
            className="flex-1 resize-none bg-transparent text-sm placeholder:text-muted-foreground focus:outline-none max-h-32 py-1"
            style={{ height: "auto" }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
            }}
          />
          <button
            onClick={submit}
            disabled={!input.trim() || sending}
            className="shrink-0 w-8 h-8 rounded-lg bg-primary text-primary-foreground flex items-center justify-center transition-opacity disabled:opacity-40 hover:opacity-90"
          >
            {sending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
        <p className="text-[10px] text-muted-foreground text-center mt-2">
          Powered by Nexora · Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
