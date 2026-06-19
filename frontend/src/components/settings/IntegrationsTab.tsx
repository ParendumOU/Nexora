"use client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Plus, Loader2, CheckCircle2, AlertCircle, Pencil, Trash2, Star, Radio, MessageSquare, Clock,
} from "lucide-react";
import { INTEGRATION_TYPES, integrationDef, IntegrationItem } from "./integration-types";
import GitCredentialsSection from "./GitCredentialsSection";
import RepoImportDialog from "./RepoImportDialog";
import { useState } from "react";

type GitCredential = {
  id: string;
  name: string;
  provider: string;
  color: string;
  base_url: string | null;
  token_hint: string;
};

interface IntegrationsTabProps {
  loadingIntegrations: boolean;
  integrationsList: IntegrationItem[];
  setDefaultIntegrationPending: boolean;
  onAddIntegration: () => void;
  onEditIntegration: (item: IntegrationItem) => void;
  onDeleteIntegration: (item: { id: string; name: string }) => void;
  onSetDefault: (id: string) => void;
}

function IntegrationsTab({
  loadingIntegrations,
  integrationsList,
  setDefaultIntegrationPending,
  onAddIntegration,
  onEditIntegration,
  onDeleteIntegration,
  onSetDefault,
}: IntegrationsTabProps) {
  const [importingCred, setImportingCred] = useState<GitCredential | null>(null);

  return (
    <>
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold">External Accounts</h2>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
            Connect messaging platforms (Telegram, Slack, Discord…) to use as workflow triggers or output channels.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={onAddIntegration} className="gap-1.5 shrink-0">
          <Plus className="w-3.5 h-3.5" />Add Account
        </Button>
      </div>

      {loadingIntegrations ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />Loading…
        </div>
      ) : integrationsList.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-14 border border-dashed border-border rounded-xl text-center max-w-md">
          <div className="flex items-center gap-2">
            <Radio className="w-6 h-6 text-muted-foreground/30" />
          </div>
          <div>
            <p className="text-sm font-medium">No external accounts yet</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Add a Telegram bot or other messaging platform to use in channels
            </p>
          </div>
          <Button size="sm" onClick={onAddIntegration}>Add first account</Button>
        </div>
      ) : (
        <div className="space-y-5 max-w-xl">
          {/* Group by type */}
          {INTEGRATION_TYPES.filter(t => !t.comingSoon && integrationsList.some(i => i.integration_type === t.value)).map(({ value: type }) => {
            const def = integrationDef(type);
            const items = integrationsList.filter(i => i.integration_type === type);
            return (
              <div key={type}>
                <div className="flex items-center gap-2 mb-2">
                  <span className={cn("w-2 h-2 rounded-full", def.dot)} />
                  <span className={cn("text-xs font-semibold", def.color)}>{def.label}</span>
                  <span className="text-xs text-muted-foreground ml-auto">{items.length} account{items.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="space-y-1.5 pl-4 border-l border-border">
                  {items.map((item) => {
                    const hub = item.config.sync_hub;
                    const hubReady = hub?.setup_complete;
                    return (
                      <div key={item.id} className={cn(
                        "flex items-start gap-3 px-3 py-2.5 bg-card border rounded-lg hover:border-border/60 transition-colors",
                        item.is_default ? "border-primary/40" : "border-border"
                      )}>
                        {item.is_active
                          ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0 mt-0.5" />
                          : <AlertCircle className="w-3.5 h-3.5 text-yellow-400 shrink-0 mt-0.5" />}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-sm font-medium truncate">{item.name}</p>
                            {item.is_default && (
                              <Badge variant="default" className="text-[10px] gap-1 h-4 px-1.5 shrink-0">
                                <Star className="w-2 h-2" />Default
                              </Badge>
                            )}
                            {(item.pending_count ?? 0) > 0 && (
                              <Badge variant="outline" className="text-[10px] gap-1 h-4 px-1.5 shrink-0 text-orange-400 border-orange-400/40">
                                <Clock className="w-2 h-2" />{item.pending_count} pending
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground flex items-center gap-1.5 mt-0.5">
                            <MessageSquare className="w-2.5 h-2.5" />
                            {item.integration_type}
                            {item.config.token && (
                              <span className="text-muted-foreground/60 font-mono truncate max-w-[140px]">· {item.config.token as string}</span>
                            )}
                          </p>
                          {item.integration_type === "telegram" && (
                            <p className="text-xs flex items-center gap-1 mt-0.5">
                              {hubReady
                                ? <><CheckCircle2 className="w-2.5 h-2.5 text-green-400" /><span className="text-green-400">Sync hub active · {Object.keys(hub?.project_topics ?? {}).length} project(s)</span></>
                                : item.is_default
                                  ? <><AlertCircle className="w-2.5 h-2.5 text-yellow-400" /><span className="text-yellow-400">Waiting for group setup — send /start to the bot</span></>
                                  : <span className="text-muted-foreground/60">Set as default to enable sync hub</span>}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => !item.is_default && onSetDefault(item.id)}
                            className={cn(
                              "p-1.5 rounded transition-colors",
                              item.is_default
                                ? "text-primary cursor-default"
                                : "text-muted-foreground hover:bg-accent hover:text-primary"
                            )}
                            title={item.is_default ? "Default integration" : "Set as default"}
                            disabled={setDefaultIntegrationPending}
                          >
                            <Star className={cn("w-3.5 h-3.5", item.is_default && "fill-current")} />
                          </button>
                          <button
                            onClick={() => onEditIntegration(item)}
                            className="p-1.5 rounded hover:bg-accent transition-colors text-muted-foreground"
                            title="Edit account"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => onDeleteIntegration({ id: item.id, name: item.name })}
                            className="p-1.5 rounded hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="border-t border-border pt-6">
        <GitCredentialsSection onImport={setImportingCred} />
      </div>

      <RepoImportDialog credential={importingCred} onClose={() => setImportingCred(null)} />

      <div className="p-4 bg-accent/20 border border-border rounded-lg space-y-3 max-w-xl">
        <div className="space-y-1">
          <p className="text-xs font-semibold flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 text-primary" />Using in channels
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Once configured here, external accounts appear in the workflow trigger selector under <strong className="text-foreground">External Chat</strong>.
            Each workflow can be linked to a specific bot or account — the platform is handled automatically in the backend.
          </p>
        </div>
        <div className="space-y-1 border-t border-border pt-3">
          <p className="text-xs font-semibold flex items-center gap-1.5">
            <Star className="w-3.5 h-3.5 text-primary" />Sync Hub (Telegram Premium)
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Mark a Telegram bot as <strong className="text-foreground">Default</strong> to activate the Sync Hub.
            Send <code className="text-[10px] bg-accent px-1 rounded">/start</code> to the bot, follow the setup steps,
            and your projects will each get a topic thread — keeping your entire workspace mirrored in Telegram.
          </p>
        </div>
      </div>
    </>
  );
}

export default IntegrationsTab;
