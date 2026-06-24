"use client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Plus, Loader2, Zap, ChevronDown, ChevronRight, ArrowDown, Star, Pencil, Trash2, AlertTriangle,
} from "lucide-react";
import { ProviderItem, providerDef } from "./provider-definitions";
import { ChainData } from "./ChainBuilderDialog";

interface ChainsTabProps {
  loadingChains: boolean;
  chains: ChainData[];
  providers: ProviderItem[];
  expandedChains: Set<string>;
  onNewChain: () => void;
  onEditChain: (chain: ChainData) => void;
  onDeleteChain: (chain: { id: string; name: string }) => void;
  onToggleExpanded: (id: string) => void;
}

function ChainsTab({
  loadingChains,
  chains,
  providers,
  expandedChains,
  onNewChain,
  onEditChain,
  onDeleteChain,
  onToggleExpanded,
}: ChainsTabProps) {
  // Show every saved chain. A single-step chain is valid — it pins one provider/model
  // with no fallback. Previously this required >= 2 steps, so a 1-provider chain saved
  // (201 OK, "successfully saved") but was filtered out of the list → looked like it
  // vanished. Only drop chains with zero steps (nothing to show).
  const filteredChains = chains.filter((c) => c.steps.length >= 1);

  return (
    <>
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold">Fallback Chains</h2>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
            An ordered list of accounts. On rate limit, the next is used seamlessly.
          </p>
        </div>
        <Button
          size="sm" variant="outline"
          onClick={onNewChain}
          disabled={providers.length === 0}
          className="gap-1.5 shrink-0"
        >
          <Plus className="w-3.5 h-3.5" />New Chain
        </Button>
      </div>

      {loadingChains ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />Loading…
        </div>
      ) : filteredChains.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-14 border border-dashed border-border rounded-xl text-center max-w-md">
          <div className="flex items-center gap-1">
            {["bg-orange-400","bg-blue-400","bg-green-400"].map((c,i) => (
              <span key={i} className={cn("w-2 h-2 rounded-full", c)} />
            ))}
          </div>
          <div>
            <p className="text-sm font-medium">No chains yet</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {providers.length === 0
                ? "Add accounts first, then create a chain"
                : "Group your accounts into a fallback chain"}
            </p>
          </div>
          {providers.length > 0 && (
            <Button size="sm" onClick={onNewChain}>Create first chain</Button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {filteredChains.map((chain) => {
            const expanded = expandedChains.has(chain.id);
            const hasZeroAccounts = chain.steps.some(s => (s.account_count ?? 0) === 0);
            const providerDots = chain.steps.slice(0, 4).map((s) => providerDef(s.provider_type).dot);
            const summary = chain.steps.map((s) => s.model_name ? `${s.provider_type}/${s.model_name}` : s.provider_type).join(" → ");
            return (
              <div key={chain.id} className="bg-card border border-border rounded-lg overflow-hidden">
                {/* Collapsed header — always visible */}
                <div
                  className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-accent/20 transition-colors select-none"
                  onClick={() => onToggleExpanded(chain.id)}
                >
                  <button className="text-muted-foreground shrink-0" tabIndex={-1}>
                    {expanded
                      ? <ChevronDown className="w-3.5 h-3.5" />
                      : <ChevronRight className="w-3.5 h-3.5" />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{chain.name}</span>
                      {chain.is_default && (
                        <Badge variant="default" className="text-[10px] gap-1 h-4 px-1.5 shrink-0">
                          <Star className="w-2 h-2" />Default
                        </Badge>
                      )}
                      {hasZeroAccounts && (
                        <span title="Some steps have no active accounts" className="shrink-0 flex">
                          <AlertTriangle className="w-3 h-3 text-amber-500" />
                        </span>
                      )}
                    </div>
                    {!expanded && (
                      <div className="flex items-center gap-2 mt-0.5">
                        <div className="flex items-center gap-1">
                          {providerDots.map((dot, i) => (
                            <span key={i} className={cn("w-1.5 h-1.5 rounded-full shrink-0", dot)} />
                          ))}
                          {chain.steps.length > 4 && (
                            <span className="text-[10px] text-muted-foreground">+{chain.steps.length - 4}</span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate">{summary}</p>
                      </div>
                    )}
                    {expanded && (
                      <p className="text-xs text-muted-foreground mt-0.5">{chain.steps.length} step{chain.steps.length !== 1 ? "s" : ""}</p>
                    )}
                  </div>
                  {/* Action buttons — stop propagation so they don't toggle expand */}
                  <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => onEditChain(chain)}
                      className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground"
                      title="Edit chain"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => onDeleteChain({ id: chain.id, name: chain.name })}
                      className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground"
                      title="Delete chain"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Expanded body — 3-column grid */}
                {expanded && (
                  <div className="px-4 pb-3 pt-1 border-t border-border">
                    <div className="grid grid-cols-3 gap-2">
                      {chain.steps.map((step, idx) => {
                        const def = providerDef(step.provider_type);
                        return (
                          <div key={idx} className={cn("flex flex-col gap-1 px-3 py-2 bg-accent/20 border rounded-lg", (step.account_count ?? 0) === 0 ? "border-amber-500/50" : "border-border")}>
                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px] font-mono text-muted-foreground w-3 shrink-0">{idx + 1}</span>
                              <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", def.dot)} />
                              <span className={cn("text-[10px] font-medium shrink-0", def.color)}>{def.label}</span>
                            </div>
                            <p className="text-xs font-medium truncate pl-4">{step.provider_type}</p>
                            {step.model_name && (
                              <p className="text-[10px] font-mono text-muted-foreground/70 truncate pl-4">{step.model_name}</p>
                            )}
                            {(step.account_count ?? 0) > 0 ? (
                              <p className="text-[10px] text-muted-foreground/60 truncate pl-4">{step.account_count} account{step.account_count !== 1 ? "s" : ""}</p>
                            ) : (
                              <p className="flex items-center gap-1 text-[10px] text-amber-500 pl-4">
                                <AlertTriangle className="w-2.5 h-2.5 shrink-0" />no active accounts
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default ChainsTab;
