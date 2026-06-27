"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Plus, Loader2, Zap, CheckCircle2, AlertCircle, Key, Pencil, Trash2, RotateCcw, Clock,
} from "lucide-react";
import { ProviderItem, providerDef } from "./provider-definitions";

function fmtRemaining(seconds: number): string {
  seconds = Math.max(0, Math.floor(seconds));
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${seconds}s`;
}

// Live "Resets in 2h 16m" badge for a rate-limited account — ticks down once a second
// off cooling_until, so the user can see at a glance whether they can work now or when.
function CoolingBadge({ p }: { p: ProviderItem }) {
  const target = p.cooling_until ? new Date(p.cooling_until).getTime() : 0;
  const compute = () => (target ? Math.max(0, Math.round((target - Date.now()) / 1000)) : 0);
  const [remaining, setRemaining] = useState<number>(
    p.cooling_remaining_seconds ?? compute()
  );
  useEffect(() => {
    if (!target) return;
    const id = setInterval(() => setRemaining(compute()), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.cooling_until]);
  if (!target || remaining <= 0) return null;
  return (
    <span
      title={`Rate-limited${p.last_error ? `: ${p.last_error}` : ""}. Resets ${new Date(target).toLocaleTimeString()}`}
      className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded px-1.5 py-0.5 shrink-0 cursor-help"
    >
      <Clock className="w-2.5 h-2.5" />
      Resets in {fmtRemaining(remaining)}
    </span>
  );
}

interface AccountsTabProps {
  loadingProviders: boolean;
  providers: ProviderItem[];
  grouped: Record<string, ProviderItem[]>;
  onAddAccount: () => void;
  onEditProvider: (p: ProviderItem) => void;
  onDeleteProvider: (p: { id: string; name: string }) => void;
  onRestoreProvider: (id: string) => void;
  onPurgeProvider: (p: { id: string; name: string }) => void;
}

function AccountsTab({
  loadingProviders,
  providers,
  grouped,
  onAddAccount,
  onEditProvider,
  onDeleteProvider,
  onRestoreProvider,
  onPurgeProvider,
}: AccountsTabProps) {
  return (
    <>
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold">AI Accounts</h2>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
            Claude, Gemini and Codex connect via OAuth — no API key needed.
            OpenAI, DeepSeek, Groq and more use API keys.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={onAddAccount} className="gap-1.5 shrink-0">
          <Plus className="w-3.5 h-3.5" />Add Account
        </Button>
      </div>

      {loadingProviders ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />Loading…
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-14 border border-dashed border-border rounded-xl text-center max-w-md">
          <div className="flex items-center gap-1">
            {["bg-orange-400","bg-emerald-400","bg-blue-400","bg-green-400","bg-indigo-400"].map((c,i) => (
              <span key={i} className={cn("w-2 h-2 rounded-full", c)} />
            ))}
          </div>
          <div>
            <p className="text-sm font-medium">No accounts yet</p>
            <p className="text-xs text-muted-foreground mt-0.5">Connect Claude or Gemini via OAuth, or add any provider with an API key</p>
          </div>
          <Button size="sm" onClick={onAddAccount}>Add first account</Button>
        </div>
      ) : (
        <div className="space-y-5 max-w-xl">
          {Object.entries(grouped).sort(([, a], [, b]) => {
            const aActive = a.some(p => p.is_active);
            const bActive = b.some(p => p.is_active);
            return aActive === bActive ? 0 : aActive ? -1 : 1;
          }).map(([type, items]) => {
            const def = providerDef(type);
            // Active first, then inactive
            const sorted = [...items].sort((a, b) => {
              if (a.is_active === b.is_active) return 0;
              return a.is_active ? -1 : 1;
            });
            return (
              <div key={type}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={cn("w-2 h-2 rounded-full", def.dot)} />
                  <span className={cn("text-xs font-semibold", def.color)}>{def.label}</span>
                  {def.oauth && (
                    <span className="text-[10px] text-primary font-medium">OAuth</span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">{items.length} account{items.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="space-y-1.5 pl-4 border-l border-border">
                  {sorted.map((p) => (
                    <div key={p.id} className={cn(
                      "flex items-center gap-3 px-3 py-2.5 bg-card border border-border rounded-lg transition-colors",
                      p.is_active ? "hover:border-border/60" : "opacity-50"
                    )}>
                      {(() => {
                        const cooling = !!p.cooling_until && (p.cooling_remaining_seconds ?? 0) > 0;
                        if (!p.is_active) return <AlertCircle className="w-3.5 h-3.5 text-yellow-400 shrink-0" />;
                        if (cooling) return <Clock className="w-3.5 h-3.5 text-amber-400 shrink-0" />;
                        return <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />;
                      })()}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium truncate">{p.name}</p>
                          {!p.is_active && (
                            <span className="text-[10px] font-medium text-yellow-500 bg-yellow-500/10 border border-yellow-500/20 rounded px-1.5 py-0.5 shrink-0">Inactive</span>
                          )}
                          <CoolingBadge p={p} />
                          {/* Only show a hard "Auth error" when the account isn't merely cooling
                              (a rate-limit reset is shown as the amber Resets-in badge instead). */}
                          {p.last_error && !(p.cooling_until && (p.cooling_remaining_seconds ?? 0) > 0) && (
                            <span
                              title={`Error: ${p.last_error}`}
                              className="text-[10px] font-medium text-red-400 bg-red-400/10 border border-red-400/20 rounded px-1.5 py-0.5 shrink-0 cursor-help"
                            >
                              Auth error
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground flex items-center gap-1.5 mt-0.5">
                          {p.auth_type === "oauth"
                            ? <><Zap className="w-2.5 h-2.5 text-primary" />OAuth</>
                            : <><Key className="w-2.5 h-2.5" />API key</>}
                          {p.model_name && (
                            <span className="text-muted-foreground/60 font-mono truncate max-w-[120px]">· {p.model_name}</span>
                          )}
                        </p>
                      </div>
                      {p.is_active ? (
                        <>
                          <button
                            onClick={() => onEditProvider(p)}
                            className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground"
                            title="Edit account"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => onDeleteProvider({ id: p.id, name: p.name })}
                            className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground"
                            title="Remove account"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => onRestoreProvider(p.id)}
                            className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
                            title="Restore account"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => onPurgeProvider({ id: p.id, name: p.name })}
                            className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground"
                            title="Permanently delete account"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Rate limit info */}
      <div className="p-4 bg-accent/20 border border-border rounded-lg space-y-1 max-w-xl">
        <p className="text-xs font-semibold flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-primary" />Auto Rate-Limit Fallback
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          When an account hits its rate limit, Nexora switches to the next in your chain automatically. The limited account cools down for 60 s, then is retried.
          Build chains in the <strong className="text-foreground">Fallback Chains</strong> tab.
        </p>
      </div>
    </>
  );
}

export default AccountsTab;
