"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, Loader2, ShieldAlert, ThumbsDown, Download, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { RiskAcknowledgmentRequired } from "@/lib/api";

export interface RiskAckDialogProps {
  /** The parsed 409 detail; when null the dialog is closed. */
  risk: RiskAcknowledgmentRequired | null;
  /** True while the "Import anyway" re-call is in flight. */
  busy?: boolean;
  /** User confirmed — re-import with acknowledge_risk=true. */
  onConfirm: () => void;
  /** User cancelled / dismissed (escape, overlay, Cancel). */
  onCancel: () => void;
}

/**
 * At-your-own-risk confirmation for low-reputation marketplace imports
 * (GitLab #158). Shown when POST /marketplace/import returns 409 with
 * `error: "risk_acknowledgment_required"`. Styled by `warning_level`
 * (amber = elevated, red = high), surfaces the marketplace disclaimer +
 * message, and lists which reputation signals tripped the gate.
 */
export function RiskAckDialog({ risk, busy = false, onConfirm, onCancel }: RiskAckDialogProps) {
  const open = risk !== null;
  const high = risk?.warning_level === "high";

  // Colour-coded by severity. Tailwind needs literal class strings, so branch.
  const accent = high
    ? { ring: "border-red-500/40", icon: "text-red-400", iconBg: "bg-red-500/10", badge: "bg-red-500/15 text-red-300 border-red-500/30" }
    : { ring: "border-amber-500/40", icon: "text-amber-400", iconBg: "bg-amber-500/10", badge: "bg-amber-500/15 text-amber-300 border-amber-500/30" };

  const signals: { icon: typeof ThumbsDown; label: string }[] = [];
  if (risk?.below_like_threshold) signals.push({ icon: ThumbsDown, label: "Few or no community likes" });
  if (risk?.below_download_threshold) signals.push({ icon: Download, label: "Few or no installs" });
  if (risk?.trust_tier === "new" || risk?.trust_tier === "low") {
    signals.push({ icon: UserPlus, label: `New / low-reputation publisher (${risk.trust_tier})` });
  }

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o && !busy) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-full max-w-md bg-card border rounded-xl shadow-lg p-5 space-y-4 animate-fade-in",
            accent.ring,
          )}
          onEscapeKeyDown={(e) => { if (busy) e.preventDefault(); }}
        >
          <div className="flex items-start gap-3">
            <div className={cn("flex items-center justify-center w-9 h-9 rounded-full shrink-0 mt-0.5", accent.iconBg)}>
              {high ? <ShieldAlert className={cn("w-4 h-4", accent.icon)} /> : <AlertTriangle className={cn("w-4 h-4", accent.icon)} />}
            </div>
            <div className="min-w-0">
              <Dialog.Title className="text-sm font-semibold flex items-center gap-2">
                Install at your own risk
                {risk && (
                  <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded border uppercase tracking-wide", accent.badge)}>
                    {risk.warning_level}
                  </span>
                )}
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-1 leading-relaxed">
                <code className="font-mono text-foreground/90 break-all">{risk?.slug}</code>
                {risk?.type ? ` (${risk.type})` : ""} has little or no community track record.
              </Dialog.Description>
            </div>
          </div>

          {signals.length > 0 && (
            <div className="space-y-1.5 rounded-lg border border-border bg-background px-3 py-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Why this warning</p>
              {signals.map((s, i) => {
                const Icon = s.icon;
                return (
                  <div key={i} className="flex items-center gap-2 text-xs text-foreground/80">
                    <Icon className={cn("w-3.5 h-3.5 shrink-0", accent.icon)} />
                    <span>{s.label}</span>
                  </div>
                );
              })}
            </div>
          )}

          {risk?.disclaimer && (
            <p className="text-[11px] text-muted-foreground leading-relaxed border-l-2 border-border pl-3">
              {risk.disclaimer}
            </p>
          )}

          {risk?.message && (
            <p className="text-xs text-foreground/80 leading-relaxed">{risk.message}</p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={onConfirm}
              disabled={busy}
              className={cn(high && "bg-red-600 hover:bg-red-600/90 text-white")}
            >
              {busy && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
              Import anyway
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
