"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { integrationsApi, agentsApi, type TelegramConversation } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ArrowLeft, Loader2, MessageSquare, Save, Trash2, ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Select from "@radix-ui/react-select";
import * as Tabs from "@radix-ui/react-tabs";

interface Integration {
  id: string;
  name: string;
  integration_type: string;
  config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

interface Agent { id: string; name: string; agent_type: string; }

function agentDisplayName(a: Agent): string {
  return a.name.replace(/\s*[—–-]\s*Project Manager$/i, "").trim();
}

function Switch({ checked, onChange, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={e => { e.stopPropagation(); onChange(!checked); }}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200",
        checked ? "bg-primary" : "bg-muted",
        disabled && "opacity-50 cursor-not-allowed",
      )}
    >
      <span className={cn(
        "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200",
        checked ? "translate-x-4" : "translate-x-0",
      )} />
    </button>
  );
}

// ─── Settings Tab ──────────────────────────────────────────────────────────────

function SettingsTab({ channel, agents }: { channel: Integration; agents: Agent[] }) {
  const qc = useQueryClient();
  const cfg = channel.config;

  const [name, setName] = useState(channel.name);
  const [botToken, setBotToken] = useState((cfg.bot_token as string) ?? "");
  const [agentId, setAgentId] = useState((cfg.channel_agent_id as string) ?? "");
  const [allowedRaw, setAllowedRaw] = useState(
    ((cfg.allowed_chat_ids as number[]) ?? []).join(", ")
  );

  useEffect(() => {
    setName(channel.name);
    setBotToken((channel.config.bot_token as string) ?? "");
    setAgentId((channel.config.channel_agent_id as string) ?? "");
    setAllowedRaw(((channel.config.allowed_chat_ids as number[]) ?? []).join(", "));
  }, [channel.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => {
      const allowed = allowedRaw
        .split(/[,\s]+/)
        .map(s => s.trim())
        .filter(Boolean)
        .map(Number)
        .filter(n => !isNaN(n));
      return integrationsApi.update(channel.id, {
        name,
        config: { bot_token: botToken || undefined, channel_agent_id: agentId, allowed_chat_ids: allowed },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel", channel.id] });
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Saved");
    },
    onError: () => toast.error("Failed to save"),
  });

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-2xl space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Name</label>
          <Input value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Bot token</label>
          <Input
            value={botToken}
            onChange={e => setBotToken(e.target.value)}
            className="h-8 text-sm font-mono"
            placeholder="1234567890:AAF… (leave blank to keep existing)"
          />
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Agent</label>
        <Select.Root value={agentId} onValueChange={setAgentId}>
          <Select.Trigger className="flex h-8 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 text-sm focus:outline-none">
            <Select.Value placeholder="Select agent…" />
            <ChevronDown className="w-3.5 h-3.5 opacity-50" />
          </Select.Trigger>
          <Select.Content position="popper" sideOffset={4} className="z-[200] w-[var(--radix-select-trigger-width)] max-h-52 overflow-y-auto rounded-lg border border-border bg-card shadow-sm p-1">
            {agents.map(a => (
              <Select.Item key={a.id} value={a.id} className="px-3 py-1.5 text-xs rounded cursor-pointer outline-none data-[highlighted]:bg-accent">
                <Select.ItemText>{agentDisplayName(a)}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Allowed chat IDs</label>
        <Input
          value={allowedRaw}
          onChange={e => setAllowedRaw(e.target.value)}
          className="h-8 text-sm font-mono"
          placeholder="123456789, -100987654321"
        />
        <p className="text-[10px] text-muted-foreground">
          Comma-separated Telegram user or group IDs. Empty = allow all (DMs only unless a group ID is listed).
          Accepted via the access-code flow automatically.
        </p>
      </div>
      <div className="flex justify-end">
        <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending} className="gap-1.5">
          {save.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Save settings
        </Button>
      </div>
    </div>
  );
}

// ─── Conversations Tab ─────────────────────────────────────────────────────────

function ConversationsTab({ channelId }: { channelId: string }) {
  const router = useRouter();
  const qc = useQueryClient();

  const { data: conversations = [], isLoading } = useQuery<TelegramConversation[]>({
    queryKey: ["channel-conversations", channelId],
    queryFn: () => integrationsApi.conversations(channelId).then(r => r.data),
    refetchInterval: 8000,
  });

  const del = useMutation({
    mutationFn: (chatId: string) => integrationsApi.deleteConversation(channelId, chatId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-conversations", channelId] });
      toast.success("Conversation deleted");
    },
    onError: () => toast.error("Failed to delete"),
  });

  if (isLoading) return (
    <div className="flex items-center justify-center h-32 text-muted-foreground">
      <Loader2 className="w-4 h-4 animate-spin mr-2" />Loading…
    </div>
  );

  if (conversations.length === 0) return (
    <div className="flex flex-col items-center justify-center h-48 gap-2 text-muted-foreground">
      <MessageSquare className="w-8 h-8 opacity-20" />
      <p className="text-sm">No conversations yet</p>
      <p className="text-xs">Activate this channel and send a message on Telegram</p>
    </div>
  );

  return (
    <div className="flex-1 overflow-y-auto divide-y divide-border">
      {conversations.map(conv => {
        const initial = (conv.title || "?").charAt(0).toUpperCase();
        const ts = new Date(conv.updated_at);
        const isToday = ts.toDateString() === new Date().toDateString();
        const timeLabel = isToday
          ? ts.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
          : ts.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        const isAgent = conv.last_message_role === "assistant";
        const preview = (conv.last_message ?? "")
          .replace(/<\s*final\s*\/?\s*>/gi, "")
          .trim();

        return (
          <div
            key={conv.chat_id}
            onClick={() => router.push(`/chat/${conv.chat_id}`)}
            className="group flex items-center gap-3 px-6 py-3.5 cursor-pointer hover:bg-accent/20 transition-colors"
          >
            <div className="w-9 h-9 rounded-full bg-accent flex items-center justify-center shrink-0 text-sm font-semibold select-none">
              {initial}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{conv.title}</p>
              <p className="text-xs text-muted-foreground truncate">
                {isAgent && <span className="mr-1">Agent:</span>}
                {preview || <span className="italic opacity-50">No messages yet</span>}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              <span className="text-[10px] text-muted-foreground">{timeLabel}</span>
              <button
                onClick={e => { e.stopPropagation(); del.mutate(conv.chat_id); }}
                disabled={del.isPending}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-destructive/20 hover:text-destructive text-muted-foreground"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function ChannelDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

  const { data: channel, isLoading } = useQuery<Integration>({
    queryKey: ["channel", id],
    queryFn: () => integrationsApi.list().then(r => {
      const all = r.data as Integration[];
      const found = all.find(i => i.id === id);
      if (!found) throw new Error("Not found");
      return found;
    }),
    enabled: !!id,
  });

  const { data: agentsRaw = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });
  const agents = agentsRaw.filter(a => a.agent_type === "project_manager");

  const toggleBot = useMutation({
    mutationFn: () =>
      channel?.is_active ? integrationsApi.stopBot(id) : integrationsApi.startBot(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel", id] });
      qc.invalidateQueries({ queryKey: ["integrations"] });
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to toggle bot");
    },
  });

  if (isLoading || !channel) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3 shrink-0">
        <button
          onClick={() => router.push("/channels")}
          className="p-1.5 rounded hover:bg-accent text-muted-foreground transition-colors shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="p-1.5 rounded-lg border text-blue-400 bg-blue-500/10 border-blue-500/20 shrink-0">
          <MessageSquare className="w-3.5 h-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-semibold truncate">{channel.name}</h1>
          <p className="text-xs text-muted-foreground">Telegram</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-muted-foreground hidden sm:block">
            {channel.is_active ? "Active" : "Inactive"}
          </span>
          <Switch
            checked={channel.is_active}
            onChange={() => toggleBot.mutate()}
            disabled={toggleBot.isPending}
          />
        </div>
      </div>

      <Tabs.Root defaultValue="conversations" className="flex flex-col flex-1 overflow-hidden">
        <Tabs.List className="flex px-4 gap-0.5 border-b border-border shrink-0">
          {[["conversations", "Conversations"], ["settings", "Settings"]] .map(([v, l]) => (
            <Tabs.Trigger
              key={v}
              value={v}
              className="px-3 py-2.5 text-xs font-medium text-muted-foreground data-[state=active]:text-foreground data-[state=active]:border-b-2 data-[state=active]:border-primary -mb-px transition-colors"
            >
              {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="conversations" className="flex flex-col flex-1 overflow-hidden data-[state=inactive]:hidden">
          <ConversationsTab channelId={id} />
        </Tabs.Content>
        <Tabs.Content value="settings" className="flex flex-col flex-1 overflow-hidden data-[state=inactive]:hidden">
          <SettingsTab channel={channel} agents={agents} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
