"use client";
import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { integrationsApi, orgsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { Loader2, Check, X, UserCheck, Clock, ShieldOff, Plus } from "lucide-react";
import { integrationDef, IntegrationItem } from "./integration-types";
import { useAuthStore } from "@/store/auth";

interface PendingRecord {
  id: string;
  tg_user_id: string;
  tg_username: string | null;
  tg_display_name: string | null;
  code: string;
  status: "pending" | "accepted" | "revoked";
  linked_user: { id: string; full_name: string; email: string; avatar_emoji: string | null } | null;
  created_at: string;
}

interface OrgMember {
  user_id: string;
  full_name: string;
  email: string;
  avatar_url: string | null;
  avatar_emoji: string | null;
  telegram_user_id: string | null;
  role: string;
}

function EditIntegrationDialog({ integration, onClose }: { integration: IntegrationItem | null; onClose: () => void }) {
  const qc = useQueryClient();
  const orgId = useAuthStore(s => s.activeOrg?.id);

  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [allowedIds, setAllowedIds] = useState<number[]>([]);
  const [rawIds, setRawIds] = useState("");
  const [acceptCode, setAcceptCode] = useState("");

  useEffect(() => {
    if (integration) {
      setName(integration.name);
      setToken("");
      const ids = (integration.config.allowed_chat_ids as unknown as number[]) ?? [];
      setAllowedIds(ids);
      setRawIds(ids.join(", "));
    }
  }, [integration?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isTelegram = integration?.integration_type === "telegram";

  const { data: pendingData = [], refetch: refetchPending } = useQuery({
    queryKey: ["integration-pending", integration?.id],
    queryFn: () => integrationsApi.listPending(integration!.id).then(r => r.data as PendingRecord[]),
    enabled: !!integration && isTelegram,
    refetchInterval: 10000,
  });

  const { data: members = [] } = useQuery({
    queryKey: ["org-members", orgId],
    queryFn: () => orgsApi.members(orgId!).then(r => r.data as OrgMember[]),
    enabled: !!orgId && isTelegram,
  });

  const linkedMembers = members.filter(m => m.telegram_user_id);

  const save = useMutation({
    mutationFn: () => {
      if (!integration) return Promise.reject();
      const config: Record<string, unknown> = { allowed_chat_ids: allowedIds };
      if (token.trim()) config.token = token.trim();
      return integrationsApi.update(integration.id, { name, config });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Integration saved");
      onClose();
    },
    onError: () => toast.error("Failed to save"),
  });

  const acceptMutation = useMutation({
    mutationFn: (code: string) => integrationsApi.accept(integration!.id, code),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      refetchPending();
      setAcceptCode("");
      toast.success("User accepted");
    },
    onError: () => toast.error("Invalid or already used code"),
  });

  const revokeMutation = useMutation({
    mutationFn: (pendingId: string) => integrationsApi.revokePending(integration!.id, pendingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      refetchPending();
      toast.success("Access revoked");
    },
    onError: () => toast.error("Failed to revoke"),
  });

  const toggleMember = (tgUserId: string) => {
    const id = parseInt(tgUserId);
    setAllowedIds(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
      setRawIds(next.join(", "));
      return next;
    });
  };

  const handleRawChange = (val: string) => {
    setRawIds(val);
    setAllowedIds(val.split(",").map(s => parseInt(s.trim())).filter(Boolean));
  };

  const def = integration ? integrationDef(integration.integration_type) : null;
  const pendingCount = pendingData.filter(p => p.status === "pending").length;

  return (
    <Dialog.Root open={!!integration} onOpenChange={(o) => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-2xl bg-card border border-border rounded-xl shadow-2xl p-6 max-h-[85vh] overflow-y-auto">
          <Dialog.Title className="text-sm font-semibold flex items-center gap-2 mb-5">
            {def && <span className={cn("w-2 h-2 rounded-full", def.dot)} />}
            Edit {def?.label ?? ""} Account
          </Dialog.Title>

          {/* Basic Config */}
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Account name</label>
              <Input value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" />
            </div>
            {isTelegram && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Bot token <span className="opacity-50">(leave blank to keep existing)</span>
                </label>
                <Input
                  value={token}
                  onChange={e => setToken(e.target.value)}
                  className="h-8 text-sm font-mono"
                  placeholder="123456:ABC-DEF..."
                />
              </div>
            )}
          </div>

          {/* Telegram Access Control */}
          {isTelegram && (
            <div className="mt-6 space-y-5">

              {/* Allowed Users */}
              <div className="border-t border-border pt-5">
                <p className="text-xs font-semibold mb-3 flex items-center gap-1.5">
                  <UserCheck className="w-3.5 h-3.5 text-primary" />
                  Allowed Users
                </p>

                {linkedMembers.length > 0 && (
                  <div className="mb-4 space-y-1.5">
                    <p className="text-xs text-muted-foreground mb-2">Nexora members with Telegram linked</p>
                    {linkedMembers.map(m => {
                      const isAllowed = allowedIds.includes(parseInt(m.telegram_user_id!));
                      return (
                        <div key={m.user_id} className={cn(
                          "flex items-center gap-2.5 px-3 py-2 rounded-lg border text-xs transition-colors",
                          isAllowed ? "border-green-500/30 bg-green-500/5" : "border-border bg-card"
                        )}>
                          <span className="text-base leading-none">{m.avatar_emoji ?? "👤"}</span>
                          <div className="flex-1 min-w-0">
                            <p className="font-medium truncate">{m.full_name}</p>
                            <p className="text-muted-foreground font-mono">TG: {m.telegram_user_id}</p>
                          </div>
                          {isAllowed ? (
                            <button
                              onClick={() => toggleMember(m.telegram_user_id!)}
                              className="flex items-center gap-1 text-xs text-green-400 hover:text-destructive transition-colors"
                            >
                              <Check className="w-3 h-3" />Allowed
                            </button>
                          ) : (
                            <button
                              onClick={() => toggleMember(m.telegram_user_id!)}
                              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                            >
                              <Plus className="w-3 h-3" />Allow
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    Allowed chat IDs <span className="opacity-50">(comma-separated — empty = allow all)</span>
                  </label>
                  <Input
                    value={rawIds}
                    onChange={e => handleRawChange(e.target.value)}
                    className="h-8 text-sm font-mono"
                    placeholder="123456789, 987654321"
                  />
                </div>
              </div>

              {/* Pending Requests */}
              <div className="border-t border-border pt-5">
                <p className="text-xs font-semibold mb-3 flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-primary" />
                  Access Requests
                  {pendingCount > 0 && (
                    <span className="ml-1 px-1.5 py-0.5 text-[10px] font-bold bg-orange-500/20 text-orange-400 rounded-full">
                      {pendingCount} pending
                    </span>
                  )}
                </p>

                {pendingData.length === 0 ? (
                  <p className="text-xs text-muted-foreground mb-4">No access requests yet.</p>
                ) : (
                  <div className="space-y-1.5 mb-4">
                    {pendingData.map(p => (
                      <div key={p.id} className={cn(
                        "flex items-center gap-2.5 px-3 py-2 rounded-lg border text-xs",
                        p.status === "pending" && "border-orange-500/30 bg-orange-500/5",
                        p.status === "accepted" && "border-green-500/30 bg-green-500/5",
                        p.status === "revoked" && "border-border bg-muted/20 opacity-60",
                      )}>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-medium">
                              {p.tg_display_name || p.tg_username || `ID: ${p.tg_user_id}`}
                            </span>
                            {p.tg_username && (
                              <span className="text-muted-foreground">@{p.tg_username}</span>
                            )}
                            {p.linked_user && (
                              <span className="text-primary">· {p.linked_user.full_name}</span>
                            )}
                          </div>
                          <p className="text-muted-foreground font-mono mt-0.5">TG: {p.tg_user_id}</p>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {p.status === "pending" && (
                            <>
                              <span className="font-mono text-[11px] text-orange-400 bg-orange-500/10 px-1.5 py-0.5 rounded">
                                {p.code}
                              </span>
                              <button
                                onClick={() => acceptMutation.mutate(p.code)}
                                disabled={acceptMutation.isPending}
                                className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300 transition-colors disabled:opacity-50"
                              >
                                <Check className="w-3 h-3" />Accept
                              </button>
                              <button
                                onClick={() => revokeMutation.mutate(p.id)}
                                disabled={revokeMutation.isPending}
                                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors disabled:opacity-50"
                              >
                                <X className="w-3 h-3" />Deny
                              </button>
                            </>
                          )}
                          {p.status === "accepted" && (
                            <>
                              <span className="text-green-400 flex items-center gap-0.5">
                                <Check className="w-3 h-3" />Accepted
                              </span>
                              <button
                                onClick={() => revokeMutation.mutate(p.id)}
                                disabled={revokeMutation.isPending}
                                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors disabled:opacity-50 ml-2"
                              >
                                <ShieldOff className="w-3 h-3" />Revoke
                              </button>
                            </>
                          )}
                          {p.status === "revoked" && (
                            <span className="text-muted-foreground flex items-center gap-0.5">
                              <X className="w-3 h-3" />Revoked
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex gap-2">
                  <Input
                    value={acceptCode}
                    onChange={e => setAcceptCode(e.target.value.toUpperCase())}
                    placeholder="Accept by code (e.g. A1B2C3)"
                    className="h-8 text-sm font-mono flex-1"
                    maxLength={6}
                    onKeyDown={e => {
                      if (e.key === "Enter" && acceptCode.length === 6) acceptMutation.mutate(acceptCode);
                    }}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={acceptCode.length < 4 || acceptMutation.isPending}
                    onClick={() => acceptMutation.mutate(acceptCode)}
                    className="gap-1.5"
                  >
                    {acceptMutation.isPending
                      ? <Loader2 className="w-3 h-3 animate-spin" />
                      : <Check className="w-3 h-3" />}
                    Accept
                  </Button>
                </div>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-5 mt-2 border-t border-border">
            <Button size="sm" variant="outline" onClick={onClose}>Cancel</Button>
            <Button
              size="sm"
              onClick={() => save.mutate()}
              disabled={save.isPending || !name.trim()}
              className="gap-1.5"
            >
              {save.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Save
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default EditIntegrationDialog;
