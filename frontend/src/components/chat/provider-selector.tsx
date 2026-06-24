"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { providersApi, chatsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronDown, Zap, GitMerge, User } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import * as Separator from "@radix-ui/react-separator";

const TYPE_DOT: Record<string, string> = {
  claude:  "bg-orange-400",
  gemini:  "bg-blue-400",
  openai:  "bg-green-400",
  ollama:  "bg-purple-400",
  custom:  "bg-muted-foreground",
};

interface Provider { id: string; name: string; provider_type: string; is_active: boolean; available_models?: string[] }
interface ChainStep { position: number; model_name: string | null; provider_type: string; account_count: number }
interface Chain { id: string; name: string; is_default: boolean; steps: ChainStep[] }

interface Props {
  chatId: string;
  currentChainId?: string | null;
  currentDirectProviderId?: string | null;
  side?: "top" | "bottom";
  asPill?: boolean;
}

export function ProviderSelector({ chatId, currentChainId, currentDirectProviderId, side = "bottom", asPill = false }: Props) {
  const qc = useQueryClient();

  const { data: chains = [] } = useQuery<Chain[]>({
    queryKey: ["chains"],
    queryFn: () => providersApi.chains().then((r) => r.data),
  });

  const { data: providers = [] } = useQuery<Provider[]>({
    queryKey: ["providers"],
    queryFn: () => providersApi.list().then((r) => r.data),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["chat", chatId] });

  const setChain = useMutation({
    mutationFn: (chainId: string | null) => chatsApi.setProviderChain(chatId, chainId),
    onSuccess: invalidate,
  });

  const setDirect = useMutation({
    mutationFn: (providerId: string | null) => chatsApi.setDirectProvider(chatId, providerId),
    onSuccess: invalidate,
  });

  const activeChain = chains.find((c) => c.id === currentChainId);
  const activeDirectProvider = providers.find((p) => p.id === currentDirectProviderId);
  const defaultChain = chains.find((c) => c.is_default && c.steps.length >= 1);
  const isAuto = !currentChainId && !currentDirectProviderId;

  const label = isAuto
    ? defaultChain ? `Auto (${defaultChain.name})` : "Auto"
    : activeDirectProvider?.name || activeChain?.name || "Select";

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        {asPill ? (
          <button type="button" className="outline-none">
            <span className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition-colors shrink-0 cursor-pointer select-none",
              !isAuto
                ? "border-primary/60 bg-primary/10 text-primary"
                : "border-border bg-transparent text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-accent/40"
            )}>
              <Zap className="w-3 h-3 shrink-0" />
              <span className="truncate max-w-[120px]">{label}</span>
              <ChevronDown className="w-3 h-3 opacity-60 shrink-0" />
            </span>
          </button>
        ) : (
          <button className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border bg-card hover:bg-accent hover:border-primary/30 transition-colors text-xs font-medium max-w-[200px]">
            <Zap className="w-3.5 h-3.5 text-primary shrink-0" />
            <span className="truncate">{label}</span>
            <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
          </button>
        )}
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          side={side}
          align="start"
          sideOffset={6}
          className="z-50 w-72 rounded-xl border border-border bg-card shadow-xl p-1 animate-fade-in"
        >
          {/* Auto / default */}
          <div className="px-2 py-1.5">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">Auto</p>
            <button
              onClick={() => { setChain.mutate(null); setDirect.mutate(null); }}
              className={cn(
                "flex items-center gap-2 w-full px-2.5 py-2 rounded-lg text-sm transition-colors",
                isAuto ? "bg-primary/10 text-primary" : "hover:bg-accent text-foreground"
              )}
            >
              <Zap className="w-3.5 h-3.5" />
              <span className="flex-1 text-left">Auto{defaultChain ? ` (${defaultChain.name})` : ""}</span>
              {isAuto && <span className="text-[10px] bg-primary/20 text-primary px-1.5 rounded">active</span>}
            </button>
          </div>

          {/* Fallback chains */}
          {chains.filter((c) => c.steps.length >= 1).length > 0 && (
            <>
              <Separator.Root className="h-px bg-border my-1" />
              <div className="px-2 py-1.5">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 flex items-center gap-1">
                  <GitMerge className="w-3 h-3" />Fallback Chains
                </p>
                <div className="space-y-0.5 max-h-48 overflow-y-auto">
                  {chains.filter((c) => c.steps.length >= 1).map((c) => {
                    const isActive = currentChainId === c.id;
                    return (
                      <button
                        key={c.id}
                        onClick={() => setChain.mutate(c.id)}
                        className={cn(
                          "flex items-start gap-2 w-full px-2.5 py-2 rounded-lg text-sm transition-colors",
                          isActive ? "bg-primary/10 text-primary" : "hover:bg-accent text-foreground"
                        )}
                      >
                        <div className="flex items-center gap-0.5 pt-0.5 shrink-0">
                          {c.steps.slice(0, 3).map((s, i) => (
                            <span key={i} className={cn("w-1.5 h-1.5 rounded-full", TYPE_DOT[s.provider_type] || "bg-muted-foreground")} />
                          ))}
                          {c.steps.length > 3 && <span className="text-[10px] text-muted-foreground">+{c.steps.length - 3}</span>}
                        </div>
                        <div className="flex-1 text-left min-w-0">
                          <span className="block truncate">{c.name}</span>
                          <span className="text-[10px] text-muted-foreground truncate block">
                            {c.steps.map((s) => s.model_name ? `${s.provider_type}/${s.model_name}` : s.provider_type).join(" → ")}
                          </span>
                        </div>
                        {isActive && <span className="text-[10px] bg-primary/20 text-primary px-1.5 rounded shrink-0">active</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {/* Single account */}
          {providers.length > 0 && (
            <>
              <Separator.Root className="h-px bg-border my-1" />
              <div className="px-2 py-1.5">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1 flex items-center gap-1">
                  <User className="w-3 h-3" />Single Account
                </p>
                <p className="text-[10px] text-amber-500/80 mb-1.5 px-0.5">Tries this account first, then falls back to chain on rate limit.</p>
                <div className="space-y-0.5 max-h-48 overflow-y-auto">
                  {(providers as Provider[]).map((p) => {
                    const active = currentDirectProviderId === p.id;
                    return (
                      <button
                        key={p.id}
                        onClick={() => setDirect.mutate(p.id)}
                        className={cn(
                          "flex items-center gap-2 w-full px-2.5 py-1.5 rounded-lg text-sm transition-colors",
                          active ? "bg-primary/10 text-primary" : "hover:bg-accent text-foreground"
                        )}
                      >
                        <span className={cn("w-2 h-2 rounded-full shrink-0", TYPE_DOT[p.provider_type] || "bg-muted-foreground")} />
                        <span className="flex-1 text-left truncate">{p.name}</span>
                        {active && <span className="text-[10px] bg-primary/20 text-primary px-1.5 rounded shrink-0">active</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {chains.length === 0 && providers.length === 0 && (
            <div className="px-3 py-4 text-center text-xs text-muted-foreground">
              No accounts yet. <a href="/settings" className="text-primary underline">Add one in Settings</a>
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
