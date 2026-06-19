"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { integrationsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { Loader2 } from "lucide-react";
import { INTEGRATION_TYPES, integrationDef } from "./integration-types";

function AddIntegrationDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [intType, setIntType] = useState("telegram");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [allowedIds, setAllowedIds] = useState("");

  const def = integrationDef(intType);

  const reset = () => { setIntType("telegram"); setName(""); setToken(""); setAllowedIds(""); };

  const create = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = {};
      if (intType === "telegram") {
        config.token = token;
        if (allowedIds.trim()) {
          config.allowed_chat_ids = allowedIds.split(",").map(s => parseInt(s.trim())).filter(Boolean);
        }
      }
      return integrationsApi.create({ name, integration_type: intType, config });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Integration added");
      reset();
      onClose();
    },
    onError: () => toast.error("Failed to add integration"),
  });

  const canSubmit = name.trim() && (intType !== "telegram" || token.trim());

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o) { reset(); onClose(); } }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-card border border-border rounded-xl shadow-2xl p-6 space-y-4">
          <Dialog.Title className="text-sm font-semibold">Add External Account</Dialog.Title>

          {/* Type selector */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Platform</label>
            <div className="grid grid-cols-2 gap-1.5">
              {INTEGRATION_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => !t.comingSoon && setIntType(t.value)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs transition-colors text-left",
                    t.comingSoon ? "opacity-40 cursor-not-allowed border-border" :
                    intType === t.value ? "border-primary bg-primary/10 text-foreground" : "border-border hover:border-border/60 hover:bg-accent"
                  )}
                >
                  <span className={cn("w-2 h-2 rounded-full shrink-0", t.dot)} />
                  <span className={t.comingSoon ? "text-muted-foreground" : t.color}>{t.label}</span>
                  {t.comingSoon && <span className="ml-auto text-[9px] text-muted-foreground/60">soon</span>}
                </button>
              ))}
            </div>
            {def.hint && <p className="text-[10px] text-muted-foreground">{def.hint}</p>}
          </div>

          {/* Name */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Account name <span className="text-primary">*</span></label>
            <Input value={name} onChange={e => setName(e.target.value)} className="h-8 text-sm" placeholder="e.g. MyBot Name" />
          </div>

          {/* Telegram-specific fields */}
          {intType === "telegram" && (
            <>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Bot token <span className="text-primary">*</span></label>
                <Input value={token} onChange={e => setToken(e.target.value)} className="h-8 text-sm font-mono" placeholder="123456:ABC-DEF..." />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Allowed chat IDs <span className="opacity-50">(comma-separated, empty = all)</span></label>
                <Input value={allowedIds} onChange={e => setAllowedIds(e.target.value)} className="h-8 text-sm font-mono" placeholder="123456789, 987654321" />
              </div>
            </>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="outline" onClick={() => { reset(); onClose(); }}>Cancel</Button>
            <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending || !canSubmit} className="gap-1.5">
              {create.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Add Account
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default AddIntegrationDialog;
