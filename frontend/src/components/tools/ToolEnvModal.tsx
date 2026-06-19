"use client";
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Package, Loader2, Check, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toolEnvsApi, type ToolEnvStatus } from "@/lib/api";
import toast from "react-hot-toast";

export interface ToolEnvModalProps {
  open: boolean;
  onClose: () => void;
  /** One entry per distinct requirements set returned by an import (python_requirements). */
  requirements: ToolEnvStatus[];
  /** Optional: pack/tool name for the header. */
  label?: string;
}

/**
 * Install-time dependency modal. When a pack/tool import reports Python
 * requirements that aren't provisioned, this prompts to install them into an
 * isolated per-pack venv (POST /tool-envs/provision). Each requirements set is
 * provisioned independently (so multi-version isolation is preserved).
 */
export function ToolEnvModal({ open, onClose, requirements, label }: ToolEnvModalProps) {
  const [busy, setBusy] = useState(false);
  // env_hash → "ok" | "error" | undefined
  const [results, setResults] = useState<Record<string, "ok" | string>>({});

  const pending = requirements.filter((r) => r.env_hash && !r.provisioned);
  const disabled = requirements.some((r) => r.enabled === false);

  const installAll = async () => {
    setBusy(true);
    const next: Record<string, "ok" | string> = { ...results };
    for (const r of pending) {
      if (!r.env_hash) continue;
      try {
        const res = await toolEnvsApi.provision(r.requirements);
        next[r.env_hash] = res.data.ok ? "ok" : res.data.error || "Install failed";
      } catch (e: unknown) {
        const err = e as { response?: { data?: { detail?: string } } };
        next[r.env_hash] = err.response?.data?.detail || "Install failed";
      }
      setResults({ ...next });
    }
    setBusy(false);
    const allOk = pending.every((r) => r.env_hash && next[r.env_hash] === "ok");
    if (allOk) {
      toast.success("Dependencies installed — the tools are ready to use.");
      onClose();
    } else {
      toast.error("Some dependencies failed to install. See details in the dialog.");
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-full max-w-md bg-card border border-border rounded-xl shadow-lg p-5 space-y-4 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-full bg-primary/10 shrink-0 mt-0.5">
              <Package className="w-4 h-4 text-primary" />
            </div>
            <div>
              <Dialog.Title className="text-sm font-semibold">
                Install Python dependencies
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {label ? `“${label}” ` : "This pack "}includes tools that need Python packages.
                They install into an isolated environment, so different packs can use
                different versions without conflicts.
              </Dialog.Description>
            </div>
          </div>

          {disabled && (
            <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 text-amber-500 rounded-lg px-3 py-2 text-xs">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              Tool environments are disabled on this instance (TOOL_ENVS_ENABLED=false).
              These tools won&apos;t run until an operator enables them.
            </div>
          )}

          <div className="space-y-2 max-h-64 overflow-auto">
            {requirements.map((r, i) => {
              const res = r.env_hash ? results[r.env_hash] : undefined;
              const done = r.provisioned || res === "ok";
              return (
                <div key={r.env_hash || i} className="bg-background border border-border rounded-lg px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <code className="text-xs font-mono text-foreground/90 break-all">
                      {r.requirements.join(", ")}
                    </code>
                    {done ? (
                      <span className="flex items-center gap-1 text-xs text-emerald-400 shrink-0">
                        <Check className="w-3.5 h-3.5" /> ready
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground shrink-0">not installed</span>
                    )}
                  </div>
                  {res && res !== "ok" && (
                    <p className="text-xs text-destructive mt-1.5 break-words">{res}</p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex gap-2 justify-end pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
              {pending.length === 0 ? "Close" : "Skip"}
            </Button>
            {pending.length > 0 && (
              <Button size="sm" onClick={installAll} disabled={busy || disabled}>
                {busy ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> Installing…</>
                ) : (
                  `Install ${pending.length} ${pending.length === 1 ? "environment" : "environments"}`
                )}
              </Button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
