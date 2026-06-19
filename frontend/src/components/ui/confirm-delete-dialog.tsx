"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface ConfirmDeleteDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  loading?: boolean;
  title: string;
  description: string;
  destroys?: string[];
}

export function ConfirmDeleteDialog({
  open,
  onClose,
  onConfirm,
  loading = false,
  title,
  description,
  destroys,
}: ConfirmDeleteDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[60] w-full max-w-sm bg-card border border-border rounded-xl shadow-lg p-5 space-y-4 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-full bg-destructive/10 shrink-0 mt-0.5">
              <AlertTriangle className="w-4 h-4 text-destructive" />
            </div>
            <div>
              <Dialog.Title className="text-sm font-semibold">{title}</Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {description}
              </Dialog.Description>
            </div>
          </div>

          {destroys && destroys.length > 0 && (
            <div className="bg-destructive/5 border border-destructive/20 rounded-lg px-3 py-2.5 space-y-1.5">
              <p className="text-xs font-medium text-destructive">Will permanently delete:</p>
              <ul className="space-y-0.5">
                {destroys.map((item, i) => (
                  <li key={i} className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-muted-foreground/50 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={onConfirm}
              disabled={loading}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 gap-1.5"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Trash2 className="w-3.5 h-3.5" />
              )}
              Delete
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
