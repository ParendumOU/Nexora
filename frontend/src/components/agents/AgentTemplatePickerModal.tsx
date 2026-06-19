"use client";

import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Sparkles, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  AGENT_TEMPLATES,
  TEMPLATE_CATEGORIES,
  type AgentTemplate,
  type TemplateCategory,
} from "@/data/agentTemplates";

// ─── Types ────────────────────────────────────────────────────────────────────

export type { AgentTemplate };

export interface TemplateSelection {
  template: AgentTemplate | null; // null = start from blank
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called when user picks a template or chooses "Start from blank". */
  onSelect: (selection: TemplateSelection) => void;
}

// ─── Category pill bar ────────────────────────────────────────────────────────

const CATEGORY_ICONS: Partial<Record<TemplateCategory, string>> = {
  Productivity: "📋",
  Code: "💻",
  "Customer Support": "🎧",
  Research: "🔬",
  Data: "📊",
  Creative: "✍️",
};

// ─── Template card ────────────────────────────────────────────────────────────

function TemplateCard({
  template,
  selected,
  onClick,
}: {
  template: AgentTemplate;
  selected: boolean;
  onClick: () => void;
}) {
  const toolCount = template.suggestedTools.length;
  const skillCount = template.suggestedSkills.length;

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-start gap-3 p-4 rounded-xl border text-left transition-all w-full group",
        selected
          ? "border-primary bg-primary/5 ring-1 ring-primary/30"
          : "border-border hover:border-primary/40 hover:bg-accent/50"
      )}
    >
      <span className="text-2xl shrink-0 mt-0.5 leading-none">{template.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <span className="text-sm font-semibold leading-tight block">{template.name}</span>
            <span
              className={cn(
                "text-[10px] px-1.5 py-0.5 rounded-full border inline-block mt-1",
                selected
                  ? "bg-primary/10 text-primary border-primary/20"
                  : "bg-accent text-muted-foreground border-border/60"
              )}
            >
              {CATEGORY_ICONS[template.category as TemplateCategory] ?? ""} {template.category}
            </span>
          </div>
          {selected && (
            <div className="w-4 h-4 rounded-full bg-primary flex items-center justify-center shrink-0 mt-0.5">
              <span className="text-[9px] text-primary-foreground font-bold leading-none">✓</span>
            </div>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground mt-1.5 leading-relaxed line-clamp-2">
          {template.description}
        </p>
        {(toolCount + skillCount) > 0 && (
          <div className="flex items-center gap-2 mt-2 text-[10px] text-muted-foreground">
            {skillCount > 0 && (
              <span>{skillCount} skill{skillCount !== 1 ? "s" : ""}</span>
            )}
            {toolCount > 0 && (
              <span>{toolCount} tool{toolCount !== 1 ? "s" : ""}</span>
            )}
          </div>
        )}
      </div>
    </button>
  );
}

// ─── Modal ────────────────────────────────────────────────────────────────────

export function AgentTemplatePickerModal({ open, onClose, onSelect }: Props) {
  const [category, setCategory] = useState<TemplateCategory>("All");
  const [selected, setSelected] = useState<AgentTemplate | null>(null);

  const filtered =
    category === "All"
      ? AGENT_TEMPLATES
      : AGENT_TEMPLATES.filter((t) => t.category === category);

  const handleConfirm = () => {
    onSelect({ template: selected });
    // Reset local state for next open
    setSelected(null);
    setCategory("All");
  };

  const handleBlank = () => {
    onSelect({ template: null });
    setSelected(null);
    setCategory("All");
  };

  const handleClose = () => {
    setSelected(null);
    setCategory("All");
    onClose();
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && handleClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50
            w-full max-w-3xl bg-card border border-border rounded-2xl shadow-2xl
            overflow-hidden flex flex-col max-h-[90vh]"
        >
          {/* Header */}
          <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border shrink-0">
            <div>
              <Dialog.Title className="text-base font-semibold flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                Start from a template
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground mt-0.5">
                Pick a pre-built agent template or start from scratch.
                Fields are pre-filled and fully editable in the next step.
              </Dialog.Description>
            </div>
            <button
              onClick={handleClose}
              className="text-muted-foreground hover:text-foreground transition-colors ml-4 mt-0.5"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Category filter */}
          <div className="px-6 py-3 border-b border-border shrink-0">
            <div className="flex flex-wrap gap-1.5">
              {TEMPLATE_CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setCategory(cat)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-full border transition-colors",
                    category === cat
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                >
                  {cat !== "All" && CATEGORY_ICONS[cat as TemplateCategory]
                    ? `${CATEGORY_ICONS[cat as TemplateCategory]} `
                    : ""}
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Grid */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            <div className="grid grid-cols-2 gap-3">
              {/* Start from blank */}
              {category === "All" && (
                <button
                  onClick={handleBlank}
                  className="flex items-start gap-3 p-4 rounded-xl border border-dashed border-border
                    text-left transition-all hover:border-primary/40 hover:bg-accent/50 group"
                >
                  <span className="text-2xl shrink-0 mt-0.5 leading-none">✨</span>
                  <div className="min-w-0">
                    <span className="text-sm font-semibold leading-tight block">Start from scratch</span>
                    <p className="text-[11px] text-muted-foreground mt-1.5 leading-relaxed">
                      Blank agent — configure everything yourself.
                    </p>
                  </div>
                </button>
              )}

              {filtered.map((tpl) => (
                <TemplateCard
                  key={tpl.id}
                  template={tpl}
                  selected={selected?.id === tpl.id}
                  onClick={() => setSelected(selected?.id === tpl.id ? null : tpl)}
                />
              ))}

              {filtered.length === 0 && (
                <div className="col-span-2 flex flex-col items-center justify-center py-10 gap-2 text-muted-foreground">
                  <span className="text-2xl opacity-30">🔍</span>
                  <p className="text-sm">No templates in this category.</p>
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-border shrink-0 gap-3">
            <div className="min-w-0">
              {selected ? (
                <div className="flex items-center gap-2 text-xs text-primary">
                  <span className="text-base leading-none">{selected.icon}</span>
                  <span>
                    <strong>{selected.name}</strong> selected — fields will be pre-filled
                  </span>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {category === "All" ? "Select a template or start from scratch." : "Select a template to continue."}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={handleClose}>
                Cancel
              </Button>
              {category !== "All" && !selected && (
                <Button variant="outline" size="sm" onClick={handleBlank}>
                  Start from scratch
                </Button>
              )}
              <Button
                size="sm"
                onClick={selected ? handleConfirm : handleBlank}
                className="gap-1.5"
              >
                {selected ? "Use template" : "Start from scratch"}
                <ChevronRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
