"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { integrationsApi, agentsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Plus, Trash2, Loader2, Radio, MessageSquare, ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";

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

function CreateChannelDialog({ open, onClose, agents }: {
  open: boolean; onClose: () => void; agents: Agent[];
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [botToken, setBotToken] = useState("");
  const [agentId, setAgentId] = useState("");

  const create = useMutation({
    mutationFn: async () => {
      const res = await integrationsApi.create({
        name: name.trim(),
        integration_type: "telegram",
        config: { bot_token: botToken.trim(), channel_agent_id: agentId, allowed_chat_ids: [] },
      });
      return res.data as Integration;
    },
    onSuccess: async (integration) => {
      // Immediately start the bot if token + agent provided
      try {
        await integrationsApi.startBot(integration.id);
      } catch { /* non-fatal — user can start manually */ }
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Channel created");
      onClose();
      router.push(`/channels/${integration.id}`);
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to create channel");
    },
  });

  const canSubmit = name.trim() && botToken.trim() && agentId;

  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-sm">
          <div className="px-5 pt-5 pb-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">New Telegram Channel</Dialog.Title>
            <p className="text-xs text-muted-foreground mt-0.5">Connect an agent to a Telegram bot</p>
          </div>
          <div className="p-5 space-y-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input autoFocus value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" placeholder="Customer support bot" />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Bot token <span className="text-primary">*</span></label>
              <Input
                value={botToken}
                onChange={e => setBotToken(e.target.value)}
                className="h-8 text-sm font-mono"
                placeholder="1234567890:AAF..."
              />
              <p className="text-[10px] text-muted-foreground">Get from @BotFather on Telegram</p>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Agent <span className="text-primary">*</span></label>
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
          </div>
          <div className="flex gap-2 justify-end px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" onClick={onClose} disabled={create.isPending}>Cancel</Button>
            <Button size="sm" onClick={() => create.mutate()} disabled={!canSubmit || create.isPending}>
              {create.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}Create
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function ChannelsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const { data: allIntegrations = [], isLoading } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: () => integrationsApi.list().then(r => r.data),
  });
  const channels = allIntegrations.filter(i => i.integration_type === "telegram");

  const { data: agentsRaw = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => agentsApi.list().then(r => r.data),
  });
  const agents = agentsRaw.filter(a => a.agent_type === "project_manager");

  const toggleBot = useMutation({
    mutationFn: (ch: Integration) =>
      ch.is_active ? integrationsApi.stopBot(ch.id) : integrationsApi.startBot(ch.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integrations"] }),
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to toggle bot");
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => integrationsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Channel deleted");
    },
    onError: () => toast.error("Delete failed"),
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold">Channels</h1>
          <p className="text-sm text-muted-foreground">Connect agents to Telegram and other platforms</p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
          <Plus className="w-3.5 h-3.5" />New Channel
        </Button>
      </div>

      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-40 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading…
          </div>
        ) : channels.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60 gap-4 text-muted-foreground">
            <Radio className="w-10 h-10 opacity-20" />
            <div className="text-center">
              <p className="text-sm font-medium">No channels yet</p>
              <p className="text-xs mt-0.5">Create one to connect an agent to Telegram</p>
            </div>
            <Button size="sm" onClick={() => setCreateOpen(true)}>Create first channel</Button>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map(ch => {
              const agentId = ch.config.channel_agent_id as string | undefined;
              const agent = agentsRaw.find(a => a.id === agentId);
              return (
                <div
                  key={ch.id}
                  onClick={() => router.push(`/channels/${ch.id}`)}
                  className="flex items-center gap-4 px-6 py-3.5 hover:bg-accent/20 cursor-pointer transition-colors"
                >
                  <div className="p-2 rounded-lg border text-blue-400 bg-blue-500/10 border-blue-500/20 shrink-0">
                    <MessageSquare className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{ch.name}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {agent ? agentDisplayName(agent) : "No agent assigned"} · Telegram
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0" onClick={e => e.stopPropagation()}>
                    {ch.is_active && (
                      <span className="flex items-center gap-1 text-[10px] text-green-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />active
                      </span>
                    )}
                    <Switch
                      checked={ch.is_active}
                      onChange={() => toggleBot.mutate(ch)}
                      disabled={toggleBot.isPending}
                    />
                    <button
                      onClick={e => {
                        e.stopPropagation();
                        if (confirm(`Delete channel "${ch.name}"?`)) del.mutate(ch.id);
                      }}
                      className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive text-muted-foreground transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <CreateChannelDialog open={createOpen} onClose={() => setCreateOpen(false)} agents={agents} />
    </div>
  );
}
